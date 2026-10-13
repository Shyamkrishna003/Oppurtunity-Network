import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from applications.tests.factories import make_application
from audit.models import AuditLog
from common.throttles import ScopedThrottle
from connections.models import Connection
from connections.tests.factories import make_connection
from jobs.models import JobDetail
from notifications.models import Notification
from opportunities.models import Opportunity
from opportunities.tests.factories import make_job
from organizations.models import OrganizationMember
from organizations.tests.factories import MemberFactory
from referrals.models import ReferralRequest, ReferralStatusHistory
from referrals.tests.factories import colleague, make_referral, referral_setup
from users.models import UserProfile
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

REFERRALS = "/api/v1/referrals/requests/"
NOTE = "I worked with Rita for two years and would hire her again."


def eligible_url(job) -> str:
    return f"/api/v1/jobs/{job.pk}/eligible-referrers/"


def ask(client, job, referrer, message="Would you refer me?"):
    return client.post(
        f"/api/v1/jobs/{job.pk}/referral-requests/",
        {"referrer_id": str(referrer.pk), "message": message},
        format="json",
    )


def one(referral, action="") -> str:
    return f"{REFERRALS}{referral.pk}/{action}"


def eligible_ids(client, job) -> list[str]:
    response = client.get(eligible_url(job))
    assert response.status_code == 200
    return [person["id"] for person in response.json()["referrers"]]


def error(response) -> tuple[int, str]:
    return response.status_code, response.json()["code"]


# --- Who can be asked -------------------------------------------------------------------


def test_only_your_own_connections_at_the_organization_can_be_asked(api_as):
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    stranger_there = colleague(job, requester, connected=False)
    friend_elsewhere = UserFactory()
    make_connection(requester, friend_elsewhere)
    pending_there = colleague(job, requester, connected=False)
    make_connection(requester, pending_there, "REQUESTED")
    # The recruiter knows the owner; that says nothing to the requester.
    make_connection(people["RECRUITER"], people["OWNER"])

    response = api_as(requester).get(eligible_url(job))

    assert response.status_code == 200
    assert response.json() == {
        "referrers": [
            {
                "id": str(referrer.pk),
                "display_name": "Ravi Referrer",
                "headline": "",
                "avatar_url": None,
            }
        ],
        "remaining": 3,
    }
    for other in (stranger_there, friend_elsewhere, pending_there, people["OWNER"]):
        assert error(ask(api_as(requester), job, other)) == (422, "not_eligible")
    assert not ReferralRequest.objects.exists()


@pytest.mark.parametrize(
    "disqualify",
    ["opted_out", "hidden_membership", "left", "deactivated", "blocked", "disconnected"],
)
def test_a_connection_who_cannot_be_asked_looks_like_anyone_else(api_as, disqualify):
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    membership = OrganizationMember.objects.filter(user=referrer)
    if disqualify == "opted_out":
        UserProfile.objects.filter(pk=referrer.pk).update(accepts_referral_requests=False)
    elif disqualify == "hidden_membership":
        membership.update(is_public=False)
    elif disqualify == "left":
        membership.update(status="LEFT")
    elif disqualify == "deactivated":
        referrer.is_active = False
        referrer.save()
    elif disqualify == "blocked":
        api_as(referrer).put(f"/api/v1/users/{requester.pk}/block/")
    elif disqualify == "disconnected":
        Connection.objects.all().delete()

    assert eligible_ids(api_as(requester), job) == []
    refused = ask(api_as(requester), job, referrer)
    unknown = api_as(requester).post(
        f"/api/v1/jobs/{job.pk}/referral-requests/",
        {"referrer_id": str(uuid.uuid7()), "message": ""},
        format="json",
    )

    # Exactly the answer given for someone who does not exist: asking is not a way to find
    # out who works where, who knows whom, or who opted out.
    bodies = []
    for response in (refused, unknown):
        assert response.status_code == 422
        body = response.json()
        body.pop("request_id")
        bodies.append(body)
    assert bodies[0] == bodies[1]
    assert bodies[0]["code"] == "not_eligible"


def test_the_list_is_about_the_caller_only_and_needs_a_verified_account(api, api_as):
    job, people = referral_setup()
    other = UserFactory()

    # Someone else sees their own (empty) list, never the requester's connection.
    assert eligible_ids(api_as(other), job) == []
    assert api.get(eligible_url(job)).status_code == 401
    assert api_as(UserFactory(unverified=True)).get(eligible_url(job)).status_code == 403
    assert api_as(other).get(eligible_url(make_job())).status_code == 404  # a draft


def test_the_list_uses_a_fixed_number_of_queries(api_as, django_assert_max_num_queries):
    job, people = referral_setup()
    for _ in range(12):
        colleague(job, people["requester"])
    client = api_as(people["requester"])

    with django_assert_max_num_queries(8):
        assert len(eligible_ids(client, job)) == 13


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("personal", (422, "referrals_unavailable")),
        ("external", (422, "referrals_unavailable")),
        ("closed", (409, "not_accepting")),
        ("deadline_passed", (409, "not_accepting")),
        ("manager", (422, "own_job")),
        ("rejected", (422, "application_ended")),
        ("withdrawn", (422, "application_ended")),
    ],
)
def test_jobs_and_people_referrals_are_not_for(api_as, case, expected):
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    if case == "personal":
        job = make_job(status="PUBLISHED", creator=referrer)
    elif case == "external":
        JobDetail.objects.filter(pk=job.pk).update(
            application_method="EXTERNAL", external_url="https://example.com/apply"
        )
    elif case == "closed":
        Opportunity.objects.filter(pk=job.pk).update(status="CLOSED")
    elif case == "deadline_passed":
        Opportunity.objects.filter(pk=job.pk).update(deadline=timezone.now() - timedelta(minutes=1))
    elif case == "manager":
        requester = people["RECRUITER"]
        make_connection(requester, referrer)
    elif case in ("rejected", "withdrawn"):
        make_application(opportunity=job, applicant=requester, status=case.upper())

    client = api_as(requester)

    assert error(client.get(eligible_url(job))) == expected
    assert error(ask(client, job, referrer)) == expected
    viewer = client.get(f"/api/v1/opportunities/{job.pk}/").json()["viewer"]
    assert viewer["can_request_referral"] is False
    assert not ReferralRequest.objects.exists()


def test_the_job_page_offers_a_referral_without_saying_whether_you_know_anyone(api, api_as):
    job, people = referral_setup()

    def offered(client):
        return client.get(f"/api/v1/opportunities/{job.pk}/").json()["viewer"][
            "can_request_referral"
        ]

    assert offered(api_as(people["requester"])) is True
    assert offered(api_as(UserFactory())) is True  # knows nobody there; same answer
    assert offered(api) is False


# --- Asking -----------------------------------------------------------------------------


def test_asking_creates_the_request_and_tells_the_referrer(api_as):
    job, people = referral_setup(title="Backend Engineer")
    requester, referrer = people["requester"], people["referrer"]

    response = ask(api_as(requester), job, referrer, "We worked together at Example Labs.")

    assert response.status_code == 201
    referral = ReferralRequest.objects.get()
    body = response.json()
    assert (body["id"], body["status"]) == (str(referral.pk), "REQUESTED")
    assert body["message"] == "We worked together at Example Labs."
    assert body["opportunity"]["title"] == "Backend Engineer"
    assert (body["requester"]["id"], body["referrer"]["id"]) == (
        str(requester.pk),
        str(referrer.pk),
    )
    assert body["history"] == [
        {
            "from_status": "",
            "to_status": "REQUESTED",
            "created_at": body["history"][0]["created_at"],
        }
    ]
    assert body["viewer"] == {"is_requester": True, "is_referrer": False, "actions": ["cancel"]}
    lifetime = referral.expires_at - referral.created_at
    assert abs(lifetime - timedelta(days=14)) < timedelta(seconds=1)
    assert AuditLog.objects.filter(action="referral.requested", actor=requester).count() == 1
    # The message is personal and stays out of the audit log.
    assert "worked together" not in str(AuditLog.objects.get().metadata)

    notification = Notification.objects.get()
    assert (notification.recipient, notification.type) == (referrer, "REFERRAL_REQUESTED")
    shown = api_as(referrer).get("/api/v1/notifications/").json()["results"][0]
    assert shown["title"] == "Rita Requester asked you for a referral"
    assert shown["url"] == f"/referrals/{referral.pk}"
    # Already asked, so no longer offered.
    assert eligible_ids(api_as(requester), job) == []
    assert api_as(requester).get(eligible_url(job)).json()["remaining"] == 2


def test_one_request_per_person_and_job_ever_and_three_open_at_a_time(api_as):
    job, people = referral_setup()
    requester = people["requester"]
    client = api_as(requester)
    make_referral(job, requester, people["referrer"], "DECLINED")
    others = [colleague(job, requester) for _ in range(4)]

    again = ask(client, job, people["referrer"])
    statuses = [ask(client, job, other).status_code for other in others[:3]]
    fourth = ask(client, job, others[3])

    assert error(again) == (409, "already_requested")
    assert statuses == [201, 201, 201]  # the declined one does not count as open
    assert error(fourth) == (409, "too_many_requests")
    assert client.get(eligible_url(job)).json()["remaining"] == 0
    # One of them ending frees a place.
    ReferralRequest.objects.filter(referrer=others[0]).update(status="CANCELLED")
    assert ask(client, job, others[3]).status_code == 201


def test_asking_needs_a_verified_account_and_is_rate_limited(api, api_as, monkeypatch):
    job, people = referral_setup()
    requester = people["requester"]
    assert ask(api, job, people["referrer"]).status_code == 401
    unverified = UserFactory(unverified=True)
    make_connection(unverified, people["referrer"])
    assert ask(api_as(unverified), job, people["referrer"]).status_code == 403

    monkeypatch.setattr(ScopedThrottle, "THROTTLE_RATES", {"referral_request": "1/day"})
    client = api_as(requester)
    assert [ask(client, job, people["referrer"]).status_code for _ in range(2)] == [201, 429]


# --- Answering --------------------------------------------------------------------------


def test_the_referrer_accepts_then_makes_the_referral(api_as):
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    referral = make_referral(job, requester, referrer)
    client = api_as(referrer)

    accepted = client.post(one(referral, "accept/"))

    assert accepted.status_code == 200
    assert accepted.json()["status"] == "ACCEPTED"
    assert accepted.json()["viewer"]["actions"] == ["refer", "back_out"]
    # Agreed between the two, but the employer sees nothing yet.
    assert api_as(people["RECRUITER"]).get(one(referral)).status_code == 404

    referred = client.post(one(referral, "refer/"), {"endorsement_note": NOTE}, format="json")

    assert referred.status_code == 200
    body = referred.json()
    assert (body["status"], body["endorsement_note"]) == ("REFERRED", NOTE)
    assert body["viewer"]["actions"] == []
    assert [step["to_status"] for step in body["history"]] == [
        "REQUESTED",
        "ACCEPTED",
        "REFERRED",
    ]
    referral.refresh_from_db()
    assert referral.referred_at is not None and referral.responded_at is not None
    assert list(
        Notification.objects.filter(recipient=requester)
        .order_by("created_at")
        .values_list("type", flat=True)
    ) == ["REFERRAL_ACCEPTED", "REFERRAL_REFERRED"]
    assert set(AuditLog.objects.values_list("action", flat=True)) == {
        "referral.accepted",
        "referral.referred",
    }
    assert NOTE not in str(list(AuditLog.objects.values_list("metadata", flat=True)))


def test_each_reader_sees_only_the_words_meant_for_them(api_as):
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    referral = make_referral(
        job, requester, referrer, "REFERRED", message="Between us.", endorsement_note=NOTE
    )

    def read(user):
        body = api_as(user).get(one(referral)).json()
        return body["message"], body["endorsement_note"]

    assert read(requester) == ("Between us.", "")
    assert read(referrer) == ("Between us.", NOTE)
    assert read(people["RECRUITER"]) == ("", NOTE)
    assert api_as(people["RECRUITER"]).get(one(referral)).json()["viewer"] == {
        "is_requester": False,
        "is_referrer": False,
        "actions": [],
    }


def test_a_decline_tells_the_requester_and_carries_no_reason(api_as):
    job, people = referral_setup()
    referral = make_referral(job, people["requester"], people["referrer"])

    response = api_as(people["referrer"]).post(
        one(referral, "decline/"), {"reason": "Not a fit."}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "DECLINED"
    assert "Not a fit" not in response.content.decode()
    notification = Notification.objects.get()
    assert (notification.recipient, notification.type) == (
        people["requester"],
        "REFERRAL_DECLINED",
    )
    assert "reason" not in notification.payload


def test_cancelling_takes_the_question_away_from_the_referrer(api_as):
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    referral_id = ask(api_as(requester), job, referrer).json()["id"]
    assert Notification.objects.filter(recipient=referrer).count() == 1

    response = api_as(requester).post(f"{REFERRALS}{referral_id}/cancel/")

    assert response.json()["status"] == "CANCELLED"
    assert not Notification.objects.exists()
    assert error(api_as(referrer).post(f"{REFERRALS}{referral_id}/accept/")) == (
        409,
        "invalid_transition",
    )


def test_someone_who_agreed_can_back_out_before_referring(api_as):
    job, people = referral_setup()
    referral = make_referral(job, people["requester"], people["referrer"], "ACCEPTED")

    response = api_as(people["referrer"]).post(one(referral, "back-out/"))

    assert response.json()["status"] == "CLOSED"
    assert Notification.objects.get().type == "REFERRAL_CLOSED"
    assert Notification.objects.get().recipient == people["requester"]


def test_a_referral_needs_a_note_a_membership_and_an_open_job(api_as):
    job, people = referral_setup()
    referral = make_referral(job, people["requester"], people["referrer"], "ACCEPTED")
    client = api_as(people["referrer"])
    refer = one(referral, "refer/")

    assert client.post(refer, {}, format="json").status_code == 400
    assert client.post(refer, {"endorsement_note": "Good."}, format="json").status_code == 400

    Opportunity.objects.filter(pk=job.pk).update(status="CLOSED")
    assert error(client.post(refer, {"endorsement_note": NOTE}, format="json")) == (
        409,
        "not_accepting",
    )
    Opportunity.objects.filter(pk=job.pk).update(status="PUBLISHED")
    OrganizationMember.objects.filter(user=people["referrer"]).update(status="LEFT")
    assert error(client.post(refer, {"endorsement_note": NOTE}, format="json")) == (
        422,
        "not_a_member",
    )

    referral.refresh_from_db()
    assert (referral.status, referral.referred_at) == ("ACCEPTED", None)


# --- Who may do what --------------------------------------------------------------------

ACTIONS = ("accept/", "decline/", "cancel/", "refer/", "back-out/")


@pytest.mark.parametrize("status", ["REQUESTED", "ACCEPTED"])
def test_outsiders_and_managers_cannot_see_or_move_a_referral_not_yet_made(api_as, status):
    job, people = referral_setup()
    referral = make_referral(job, people["requester"], people["referrer"], status)
    insider = MemberFactory(organization=job.organization).user

    for user in (UserFactory(), insider, people["RECRUITER"], people["OWNER"]):
        client = api_as(user)
        assert client.get(one(referral)).status_code == 404
        for action in ACTIONS:
            body = {"endorsement_note": NOTE} if action == "refer/" else {}
            assert client.post(one(referral, action), body, format="json").status_code == 404
        assert client.get(REFERRALS, {"role": "referrer"}).json()["results"] == []
        assert client.get(REFERRALS).json()["results"] == []

    referral.refresh_from_db()
    assert referral.status == status


def test_each_person_can_only_make_their_own_moves(api_as):
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    referral = make_referral(job, requester, referrer)

    for action in ("accept/", "decline/"):
        assert api_as(requester).post(one(referral, action)).status_code == 403
    assert api_as(referrer).post(one(referral, "cancel/")).status_code == 403

    referral.refresh_from_db()
    assert referral.status == "REQUESTED"
    assert ReferralStatusHistory.objects.count() == 1


@pytest.mark.parametrize(
    "status", ["REFERRED", "APPLICATION_SUBMITTED", "INTERVIEW", "OFFER", "JOINED", "CLOSED"]
)
def test_nobody_moves_a_referral_by_hand_once_it_is_made_or_over(api_as, status):
    job, people = referral_setup()
    referral = make_referral(job, people["requester"], people["referrer"], status)

    for user in (people["requester"], people["referrer"], people["RECRUITER"]):
        for action in ACTIONS:
            if action == "back-out/" and status == "CLOSED":
                continue  # asking for the state it is already in changes nothing
            body = {"endorsement_note": NOTE} if action == "refer/" else {}
            response = api_as(user).post(one(referral, action), body, format="json")
            if status == "REFERRED" and action == "refer/":
                continue  # likewise a repeat
            assert response.status_code in (403, 404, 409), (user, action)

    referral.refresh_from_db()
    assert referral.status == status
    assert ReferralStatusHistory.objects.count() == 1


# --- Lists ------------------------------------------------------------------------------


def test_lists_show_each_side_its_own_referrals(api, api_as, django_assert_max_num_queries):
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    mine = make_referral(job, requester, referrer, "ACCEPTED")
    other_job = make_job(status="PUBLISHED", organization=job.organization, creator=referrer)
    declined = make_referral(other_job, requester, referrer, "DECLINED")
    make_referral(job, UserFactory(), colleague(job, requester))  # other people's

    sent = api_as(requester).get(REFERRALS).json()["results"]
    received = api_as(referrer).get(REFERRALS, {"role": "referrer"}).json()["results"]

    assert {row["id"] for row in sent} == {str(mine.pk), str(declined.pk)}
    assert {row["id"] for row in received} == {str(mine.pk), str(declined.pk)}
    assert api_as(referrer).get(REFERRALS).json()["results"] == []
    client = api_as(requester)
    assert [r["id"] for r in client.get(REFERRALS, {"status": "DECLINED"}).json()["results"]] == [
        str(declined.pk)
    ]
    for_job = client.get(REFERRALS, {"opportunity": str(job.pk)}).json()["results"]
    assert [row["id"] for row in for_job] == [str(mine.pk)]
    # A list row has no message and no note.
    assert not {"message", "endorsement_note"} & set(sent[0])
    for bad in ({"role": "manager"}, {"status": "MAYBE"}, {"opportunity": "x"}):
        assert client.get(REFERRALS, bad).status_code == 400
    assert api.get(REFERRALS).status_code == 401

    for _ in range(5):
        make_referral(job, requester, colleague(job, requester), "DECLINED")
    with django_assert_max_num_queries(3):
        assert len(client.get(REFERRALS).json()["results"]) == 7
