"""A made referral follows the requester's application, and the sweeps tidy up the rest."""

from datetime import timedelta

import pytest
from django.utils import timezone

from applications import services as applications
from applications.models import ApplicationStatus
from applications.tests.factories import make_application, pdf
from audit.models import AuditLog
from common.errors import InvalidTransition
from notifications.models import Notification
from opportunities.models import Opportunity
from referrals import services
from referrals.models import ReferralRequest, ReferralStatus, ReferralStatusHistory
from referrals.policies import MIRROR, OPEN, TRACKED, WORKFLOW, Actor
from referrals.tasks import sweep
from referrals.tests.factories import colleague, make_referral, referral_setup

pytestmark = pytest.mark.django_db

NOTE = "I worked with Rita for two years and would hire her again."
S = ReferralStatus


def apply_to(job, applicant):
    application, _ = applications.apply(
        applicant=applicant, opportunity_id=job.pk, resume=pdf(), cover_note=""
    )
    return application


def move(application, manager, to):
    return applications.transition(
        user=manager, application_id=application.pk, to=ApplicationStatus(to)
    )


def status_of(referral):
    referral.refresh_from_db()
    return referral.status


def told(user) -> list[str]:
    return list(
        Notification.objects.filter(recipient=user, type__startswith="REFERRAL")
        .order_by("created_at")
        .values_list("type", flat=True)
    )


# --- The state machine ------------------------------------------------------------------

REFERRER = Actor(is_requester=False, is_referrer=True)
REQUESTER = Actor(is_requester=True, is_referrer=False)
MANAGER = Actor(is_requester=False, is_referrer=False, is_manager=True)

# Every move that exists, and who makes it. Anything not listed must be refused.
ALLOWED: dict[tuple[str, str], set[str]] = {
    (S.REQUESTED, S.ACCEPTED): {"referrer"},
    (S.REQUESTED, S.DECLINED): {"referrer"},
    (S.REQUESTED, S.CANCELLED): {"requester"},
    (S.REQUESTED, S.EXPIRED): {"system"},
    (S.REQUESTED, S.CLOSED): {"system"},
    (S.ACCEPTED, S.REFERRED): {"referrer"},
    (S.ACCEPTED, S.CLOSED): {"referrer", "system"},
    **{
        (source, target): {"system"}
        for index, source in enumerate(TRACKED)
        for target in TRACKED[index + 1 :]
    },
    **{(source, S.CLOSED): {"system"} for source in TRACKED[:-1]},
}
ACTORS = {"referrer": REFERRER, "requester": REQUESTER, "manager": MANAGER, "system": None}


@pytest.mark.parametrize("source", list(S))
@pytest.mark.parametrize("target", list(S))
@pytest.mark.parametrize("who", list(ACTORS))
def test_the_transition_table(source, target, who):
    if source == target:
        return
    referral = ReferralRequest(status=source)
    allowed = who in ALLOWED.get((source, target), set())

    if allowed:
        assert WORKFLOW.apply(referral, target, actor=ACTORS[who]) is True
        assert referral.status == target
    else:
        with pytest.raises(Exception) as refused:  # noqa: PT011
            WORKFLOW.apply(referral, target, actor=ACTORS[who])
        assert refused.type.__name__ in ("InvalidTransition", "PermissionDenied")
        assert referral.status == source


def test_final_states_are_final_and_every_application_status_is_mirrored():
    for status in set(S) - OPEN:
        assert WORKFLOW.is_terminal(status)
        with pytest.raises(InvalidTransition):
            WORKFLOW.apply(ReferralRequest(status=status), S.REQUESTED, actor=None)
    assert set(MIRROR) == set(ApplicationStatus.values)


# --- Following the application ----------------------------------------------------------


def test_a_referral_follows_the_application_to_the_job(api_as):
    job, people = referral_setup(title="Backend Engineer")
    requester, referrer, recruiter = people["requester"], people["referrer"], people["RECRUITER"]
    referral = make_referral(job, requester, referrer, "REFERRED")

    application = apply_to(job, requester)

    assert status_of(referral) == "APPLICATION_SUBMITTED"
    assert referral.application == application
    for to, expected in (
        ("SCREENING", "APPLICATION_SUBMITTED"),
        ("INTERVIEW", "INTERVIEW"),
        ("OFFER", "OFFER"),
        ("HIRED", "JOINED"),
    ):
        move(application, recruiter, to)
        assert status_of(referral) == expected

    assert [step.to_status for step in referral.history.order_by("created_at")] == [
        "REQUESTED",
        "APPLICATION_SUBMITTED",
        "INTERVIEW",
        "OFFER",
        "JOINED",
    ]
    # The system made every one of those moves.
    assert not referral.history.exclude(to_status="REQUESTED").filter(actor__isnull=False).exists()
    assert AuditLog.objects.filter(action="referral.outcome", actor=None).count() == 4
    # The referrer hears that an application exists and how it ended, not each stage between.
    assert told(referrer) == ["REFERRAL_OUTCOME", "REFERRAL_OUTCOME"]
    shown = api_as(referrer).get("/api/v1/notifications/").json()["results"]
    assert shown[0]["title"] == "Rita Requester got the job: “Backend Engineer”"
    assert shown[1]["title"] == "Rita Requester applied to “Backend Engineer”"
    assert told(requester) == []


def test_referring_someone_who_already_applied_attaches_to_their_application(api_as):
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    application = make_application(opportunity=job, applicant=requester, status="INTERVIEW")
    referral = make_referral(job, requester, referrer, "ACCEPTED")

    response = api_as(referrer).post(
        f"/api/v1/referrals/requests/{referral.pk}/refer/",
        {"endorsement_note": NOTE},
        format="json",
    )

    body = response.json()
    assert body["status"] == "INTERVIEW"
    assert [step["to_status"] for step in body["history"]] == [
        "REQUESTED",
        "REFERRED",
        "INTERVIEW",
    ]
    referral.refresh_from_db()
    assert referral.application == application
    # The referrer follows the referral, not the application itself.
    assert body["application_id"] is None
    mine = api_as(requester).get(f"/api/v1/referrals/requests/{referral.pk}/").json()
    assert mine["application_id"] == str(application.pk)


@pytest.mark.parametrize("ending", ["REJECTED", "WITHDRAWN"])
@pytest.mark.parametrize("stage", ["REQUESTED", "ACCEPTED", "REFERRED", "INTERVIEW"])
def test_the_end_of_the_application_closes_every_open_referral(ending, stage):
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    application = make_application(opportunity=job, applicant=requester)
    referral = make_referral(job, requester, referrer, stage)
    finished = make_referral(job, requester, colleague(job, requester), "DECLINED")

    if ending == "REJECTED":
        move(application, people["RECRUITER"], "REJECTED")
    else:
        applications.withdraw(user=requester, application_id=application.pk)

    assert status_of(referral) == "CLOSED"
    assert status_of(finished) == "DECLINED"
    # Someone who never answered is not told about something they never took up.
    assert told(referrer) == ([] if stage == "REQUESTED" else ["REFERRAL_CLOSED"])
    assert told(requester) == []


def test_an_application_does_not_touch_referrals_not_yet_made_or_other_peoples():
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    asked = make_referral(job, requester, referrer)
    agreed = make_referral(job, requester, colleague(job, requester), "ACCEPTED")
    other = colleague(job, requester)
    someone_elses = make_referral(job, other, referrer, "REFERRED")

    application = apply_to(job, requester)
    move(application, people["RECRUITER"], "INTERVIEW")

    assert (status_of(asked), status_of(agreed)) == ("REQUESTED", "ACCEPTED")
    assert status_of(someone_elses) == "REFERRED"
    assert ReferralStatusHistory.objects.count() == 3


def test_the_people_hiring_see_who_referred_an_applicant(api_as, django_assert_max_num_queries):
    job, people = referral_setup()
    requester, referrer, recruiter = people["requester"], people["referrer"], people["RECRUITER"]
    application = make_application(opportunity=job, applicant=requester)
    referral = make_referral(
        job, requester, referrer, "APPLICATION_SUBMITTED", application=application
    )
    # Asked but never made: not the employer's business.
    make_referral(job, requester, colleague(job, requester))
    for _ in range(5):
        make_application(opportunity=job)

    with django_assert_max_num_queries(8):
        rows = api_as(recruiter).get(f"/api/v1/jobs/{job.pk}/applications/").json()["results"]

    by_id = {row["id"]: row for row in rows}
    assert by_id[str(application.pk)]["referrals"] == [
        {
            "id": str(referral.pk),
            "referrer": {
                "id": str(referrer.pk),
                "display_name": "Ravi Referrer",
                "headline": "",
                "avatar_url": None,
            },
            "endorsement_note": "I worked with them for two years.",
            "referred_at": by_id[str(application.pk)]["referrals"][0]["referred_at"],
        }
    ]
    assert sum(len(row["referrals"]) for row in rows) == 1
    detail = f"/api/v1/applications/{application.pk}/"
    assert len(api_as(recruiter).get(detail).json()["referrals"]) == 1
    # What was said about the applicant is not shown to the applicant.
    assert api_as(requester).get(detail).json()["referrals"] == []
    assert api_as(recruiter).get(f"/api/v1/referrals/requests/{referral.pk}/").status_code == 200


# --- Sweeps -----------------------------------------------------------------------------


def test_unanswered_requests_expire_once():
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    past = timezone.now() - timedelta(minutes=1)
    due = make_referral(job, requester, referrer, expires_at=past)
    fresh = make_referral(job, requester, colleague(job, requester))
    answered = make_referral(job, requester, colleague(job, requester), "ACCEPTED", expires_at=past)

    assert sweep() == 1
    assert sweep() == 0

    assert status_of(due) == "EXPIRED"
    assert (status_of(fresh), status_of(answered)) == ("REQUESTED", "ACCEPTED")
    assert told(requester) == ["REFERRAL_EXPIRED"]
    assert told(referrer) == []
    assert AuditLog.objects.filter(action="referral.expired", actor=None).count() == 1


@pytest.mark.parametrize("ended", ["closed", "deadline"])
def test_referrals_with_no_application_close_when_the_job_stops_taking_them(ended):
    job, people = referral_setup()
    requester, referrer = people["requester"], people["referrer"]
    asked = make_referral(job, requester, referrer)
    agreed = make_referral(job, requester, colleague(job, requester), "ACCEPTED")
    other = colleague(job, requester)
    made = make_referral(job, other, referrer, "REFERRED")
    applied = colleague(job, requester)
    application = make_application(opportunity=job, applicant=applied, status="INTERVIEW")
    tracking = make_referral(job, applied, referrer, "INTERVIEW", application=application)
    if ended == "closed":
        Opportunity.objects.filter(pk=job.pk).update(status="CLOSED")
    else:
        Opportunity.objects.filter(pk=job.pk).update(deadline=timezone.now() - timedelta(minutes=1))

    assert sweep() == 3
    assert sweep() == 0

    assert [status_of(r) for r in (asked, agreed, made)] == ["CLOSED"] * 3
    # An application already in the pipeline can still be decided after the job closes.
    assert status_of(tracking) == "INTERVIEW"
    move(application, people["RECRUITER"], "HIRED")
    assert status_of(tracking) == "JOINED"
    assert told(requester) == ["REFERRAL_CLOSED", "REFERRAL_CLOSED"]


def test_the_sweep_leaves_open_jobs_alone():
    job, people = referral_setup()
    make_referral(job, people["requester"], people["referrer"])

    assert services.close_for_ended_jobs() == 0
    assert services.expire_unanswered() == 0
