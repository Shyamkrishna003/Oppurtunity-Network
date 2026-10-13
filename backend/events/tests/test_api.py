from datetime import timedelta

import pytest
from django.utils import timezone

from audit.models import AuditLog
from events.models import EventDetail
from events.tests.factories import make_event
from opportunities.models import Opportunity
from opportunities.tests.factories import make_job
from organizations.tests.factories import organization_with_roles
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/opportunities/"


def detail(opportunity, action="") -> str:
    return f"{URL}{opportunity.pk}/{action}"


def at(**delta) -> str:
    return (timezone.now() + timedelta(**delta)).isoformat()


def payload(event=None, **overrides):
    """A complete in-person event: enough to publish as it stands."""
    return {
        "type": "EVENT",
        "title": "Kochi Python Meetup",
        "description": "Talks, pizza and people who build things.",
        "city": "Kochi",
        "country_code": "in",
        "event": {
            "format": "IN_PERSON",
            "start_at": at(days=7),
            "end_at": at(days=7, hours=2),
            "timezone": "Asia/Kolkata",
            "venue": "Kerala Startup Mission",
            "capacity": 40,
            **(event or {}),
        },
        **overrides,
    }


# --- Creating ---------------------------------------------------------------------------


def test_creating_an_event_makes_a_draft_with_its_detail_row(api_as):
    user = UserFactory()

    response = api_as(user).post(URL, payload())

    assert response.status_code == 201
    body = response.json()
    assert (body["type"], body["status"], body["job"]) == ("EVENT", "DRAFT", None)
    assert body["event"]["event_status"] == ""  # no registration status until published
    assert (body["event"]["format"], body["event"]["capacity"]) == ("IN_PERSON", 40)
    assert (body["event"]["venue"], body["event"]["timezone"]) == (
        "Kerala Startup Mission",
        "Asia/Kolkata",
    )
    assert (body["event"]["confirmed_count"], body["event"]["attendee_visibility"]) == (
        0,
        "ATTENDEES",
    )
    # Not chosen: it follows from the format, so filters and matching work for events too.
    assert (body["work_mode"], body["country_code"]) == ("ONSITE", "IN")
    assert body["viewer"]["can_manage"] is True
    assert body["viewer"]["can_apply"] is False

    opportunity = Opportunity.objects.get()
    assert EventDetail.objects.get().pk == opportunity.pk
    assert not hasattr(opportunity, "job")
    log = AuditLog.objects.get(action="opportunity.created")
    assert (log.actor, log.metadata) == (user, {"type": "EVENT"})


@pytest.mark.parametrize(
    ("format", "work_mode"), [("ONLINE", "REMOTE"), ("HYBRID", "HYBRID"), ("IN_PERSON", "ONSITE")]
)
def test_the_work_mode_follows_the_format_whatever_is_sent(api_as, format, work_mode):
    client = api_as(UserFactory())

    created = client.post(URL, payload(event={"format": format}, work_mode="REMOTE")).json()
    assert created["work_mode"] == work_mode

    # And keeps following it when the format changes later.
    changed = client.patch(f"{URL}{created['id']}/", {"event": {"format": "ONLINE"}}).json()
    assert changed["work_mode"] == "REMOTE"
    # An online event has nowhere to go, so the venue is dropped with it.
    assert changed["event"]["venue"] == ""


def test_an_event_for_an_organization_needs_a_posting_role(api_as):
    organization, members = organization_with_roles("RECRUITER", "MEMBER")
    body = payload(organization_id=str(organization.pk))

    assert api_as(members["MEMBER"].user).post(URL, body).status_code == 403
    assert api_as(UserFactory()).post(URL, body).status_code == 403
    created = api_as(members["RECRUITER"].user).post(URL, body)
    assert created.status_code == 201
    assert created.json()["organization"]["id"] == str(organization.pk)
    assert created.json()["posted_by"] is None


@pytest.mark.parametrize(
    ("event", "field"),
    [
        ({"format": "CONCERT"}, "event.format"),
        ({"timezone": "Mars/Olympus"}, "event.timezone"),
        ({"capacity": 0}, "event.capacity"),
        ({"capacity": -3}, "event.capacity"),
        ({"online_url": "javascript:alert(1)"}, "event.online_url"),
        ({"online_url": "not a link"}, "event.online_url"),
        ({"attendee_visibility": "EVERYONE"}, "event.attendee_visibility"),
        ({"start_at": "tomorrow"}, "event.start_at"),
        ({"venue": "x" * 201}, "event.venue"),
    ],
)
def test_create_validates_the_event(api_as, event, field):
    response = api_as(UserFactory()).post(URL, payload(event=event))

    assert response.status_code == 400
    assert list(response.json()["errors"]) == [field]
    assert not Opportunity.objects.exists()


def test_an_event_must_end_after_it_starts(api_as):
    client = api_as(UserFactory())
    backwards = {"start_at": at(days=3), "end_at": at(days=2)}

    assert client.post(URL, payload(event=backwards)).status_code == 400

    # Also when only one end is changed later.
    created = client.post(URL, payload()).json()
    moved = client.patch(f"{URL}{created['id']}/", {"event": {"end_at": at(days=1)}})
    assert (moved.status_code, list(moved.json()["errors"])) == (400, ["event.end_at"])


def test_what_the_client_cannot_set(api_as):
    response = api_as(UserFactory()).post(
        URL, payload(event={"event_status": "COMPLETED", "confirmed_count": 99})
    )

    assert response.status_code == 201
    assert response.json()["event"]["event_status"] == ""
    assert response.json()["event"]["confirmed_count"] == 0


def test_a_job_has_no_event_and_an_event_has_no_job(api_as):
    client = api_as(UserFactory())
    job_fields = {"employment_type": "FULL_TIME"}

    as_event = client.post(URL, payload(job=job_fields))
    assert (as_event.status_code, list(as_event.json()["errors"])) == (400, ["job"])
    as_job = client.post(URL, {**payload(), "type": "JOB"})
    assert (as_job.status_code, list(as_job.json()["errors"])) == (400, ["event"])

    event, job = make_event(), make_job()
    wrong = api_as(event.creator).patch(detail(event), {"job": job_fields})
    assert (wrong.status_code, list(wrong.json()["errors"])) == (400, ["job"])
    wrong = api_as(job.creator).patch(detail(job), {"event": {"venue": "Somewhere"}})
    assert (wrong.status_code, list(wrong.json()["errors"])) == (400, ["event"])
    assert not Opportunity.objects.exclude(pk__in=[event.pk, job.pk]).exists()


# --- Publishing -------------------------------------------------------------------------


def test_publishing_opens_registration_and_shows_the_event_to_everyone(api, api_as):
    event = make_event()
    assert api.get(detail(event)).status_code == 404

    response = api_as(event.creator).post(detail(event, "publish/"))

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["event"]["event_status"]) == ("PUBLISHED", "REGISTRATION_OPEN")
    assert api.get(detail(event)).status_code == 200
    assert AuditLog.objects.filter(action="opportunity.published").count() == 1

    # Publishing twice changes nothing.
    assert api_as(event.creator).post(detail(event, "publish/")).status_code == 200
    assert AuditLog.objects.filter(action="opportunity.published").count() == 1


def test_registration_waits_for_its_opening_time(api_as):
    event = make_event(event={"registration_opens_at": timezone.now() + timedelta(days=2)})

    response = api_as(event.creator).post(detail(event, "publish/"))

    assert response.json()["event"]["event_status"] == "SCHEDULED"


def test_publishing_lists_everything_an_event_still_needs(api_as):
    user = UserFactory()
    bare = api_as(user).post(URL, {"type": "EVENT", "title": "Meetup"}).json()

    response = api_as(user).post(f"{URL}{bare['id']}/publish/")

    assert (response.status_code, response.json()["code"]) == (422, "incomplete")
    assert set(response.json()["errors"]) == {
        "description",
        "event.format",
        "event.timezone",
        "event.start_at",
        "event.end_at",
    }
    assert Opportunity.objects.get().status == "DRAFT"


def test_an_event_in_a_place_needs_the_place_and_an_online_one_does_not(api_as):
    in_person = make_event(event={"venue": ""}, city="", country_code="")
    online = make_event(event={"format": "ONLINE", "venue": ""})

    response = api_as(in_person.creator).post(detail(in_person, "publish/"))
    assert set(response.json()["errors"]) == {"event.venue", "city", "country_code"}

    assert api_as(online.creator).post(detail(online, "publish/")).status_code == 200


@pytest.mark.parametrize(
    ("fields", "event", "expected"),
    [
        ({}, {"start_at": timezone.now() - timedelta(hours=1)}, {"event.start_at"}),
        ({"deadline": timezone.now() + timedelta(days=9)}, {}, {"deadline"}),
        ({"deadline": timezone.now() - timedelta(days=1)}, {}, {"deadline"}),
        (
            {"deadline": timezone.now() + timedelta(days=2)},
            {"registration_opens_at": timezone.now() + timedelta(days=3)},
            {"event.registration_opens_at"},
        ),
        (
            {},
            {"registration_opens_at": timezone.now() + timedelta(days=8)},
            {"event.registration_opens_at"},
        ),
    ],
)
def test_the_times_of_an_event_must_make_sense_to_publish(api_as, fields, event, expected):
    draft = make_event(event=event, **fields)

    response = api_as(draft.creator).post(detail(draft, "publish/"))

    assert response.status_code == 422
    assert set(response.json()["errors"]) == expected


def test_an_event_needs_no_skills_and_a_job_still_does(api_as):
    event, job = make_event(), make_job(skills=())

    assert api_as(event.creator).post(detail(event, "publish/")).status_code == 200
    refused = api_as(job.creator).post(detail(job, "publish/"))
    assert set(refused.json()["errors"]) == {"skill_ids"}


# --- Editing ----------------------------------------------------------------------------


def test_a_draft_event_is_fully_editable(api_as):
    event = make_event()

    response = api_as(event.creator).patch(
        detail(event),
        {"title": "Kochi Rust Meetup", "event": {"capacity": 10, "venue": "Infopark"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["title"], body["event"]["capacity"], body["event"]["venue"]) == (
        "Kochi Rust Meetup",
        10,
        "Infopark",
    )
    log = AuditLog.objects.get(action="opportunity.updated")
    assert log.metadata["fields"] == ["event.capacity", "event.venue", "title"]


def test_a_published_event_can_change_where_but_not_when_or_what(api_as):
    event = make_event(status="PUBLISHED")
    client = api_as(event.creator)

    allowed = client.patch(
        detail(event),
        {
            "description": "Now with lightning talks.",
            "event": {
                "venue": "Infopark, Kakkanad",
                "online_url": "https://meet.example.com/kochi",
                "attendee_visibility": "PUBLIC",
            },
        },
    )
    assert allowed.status_code == 200
    assert allowed.json()["event"]["venue"] == "Infopark, Kakkanad"

    refused = client.patch(
        detail(event),
        {
            "title": "Something else",
            "event": {"start_at": at(days=6), "format": "ONLINE", "capacity": 5},
        },
    )
    assert (refused.status_code, refused.json()["code"]) == (422, "locked_after_publish")
    # The work mode would have followed the format, so it is reported as locked too.
    assert set(refused.json()["errors"]) == {
        "title",
        "work_mode",
        "event.start_at",
        "event.format",
        "event.capacity",
    }
    event.event.refresh_from_db()
    assert event.event.format == "IN_PERSON"

    # A form that sends everything back unchanged is not tripped up by the locked fields.
    current = client.get(detail(event)).json()
    unchanged = client.patch(
        detail(event),
        {
            "title": current["title"],
            "event": {key: current["event"][key] for key in ("format", "start_at", "capacity")},
        },
    )
    assert unchanged.status_code == 200


def test_only_its_managers_may_change_an_event(api_as):
    organization, members = organization_with_roles("RECRUITER", "MEMBER")
    event = make_event(status="PUBLISHED", organization=organization, creator=members["OWNER"].user)

    for outsider in (members["MEMBER"].user, UserFactory()):
        client = api_as(outsider)
        assert client.patch(detail(event), {"description": "Hacked"}).status_code == 403
        assert client.post(detail(event, "close/"), {"reason": "CANCELLED"}).status_code == 403
    # A colleague who can post for the organization manages it too.
    assert (
        api_as(members["RECRUITER"].user)
        .patch(detail(event), {"event": {"venue": "Room 2"}})
        .status_code
        == 200
    )


# --- The link to join -------------------------------------------------------------------


def test_the_joining_link_is_only_given_to_the_people_running_the_event(api, api_as):
    link = "https://meet.example.com/secret-room"
    event = make_event(status="PUBLISHED", event={"format": "ONLINE", "online_url": link})

    mine = api_as(event.creator).get(detail(event)).json()["event"]
    assert (mine["online_url"], mine["has_online_url"]) == (link, True)

    for client in (api, api_as(UserFactory())):
        response = client.get(detail(event))
        assert response.json()["event"]["online_url"] == ""
        assert response.json()["event"]["has_online_url"] is True
        assert link not in response.content.decode()
        listed = client.get(URL, {"type": "EVENT"})
        assert link not in listed.content.decode()
    # Nor in a list, even the manager's own.
    assert link not in api_as(event.creator).get(URL).content.decode()


# --- Cancelling -------------------------------------------------------------------------


def test_closing_an_event_cancels_it_whatever_reason_is_sent(api, api_as):
    event = make_event(status="PUBLISHED")

    response = api_as(event.creator).post(detail(event, "close/"), {"reason": "FILLED"})

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["close_reason"], body["event"]["event_status"]) == (
        "CLOSED",
        "CANCELLED",
        "CANCELLED",
    )
    log = AuditLog.objects.get(action="opportunity.closed")
    assert log.metadata == {"reason": "CANCELLED"}
    # Still there for people who had the link, marked as cancelled.
    assert api.get(detail(event)).json()["event"]["event_status"] == "CANCELLED"
    # And it can be archived like any closed opportunity.
    assert api_as(event.creator).post(detail(event, "archive/")).status_code == 200


def test_nobody_can_mark_something_completed_by_hand(api_as):
    event, job = make_event(status="PUBLISHED"), make_job(status="PUBLISHED")

    for opportunity in (event, job):
        response = api_as(opportunity.creator).post(
            detail(opportunity, "close/"), {"reason": "COMPLETED"}
        )
        assert (response.status_code, response.json()["code"]) == (422, "invalid_reason")
        opportunity.refresh_from_db()
        assert opportunity.status == "PUBLISHED"


def test_a_draft_event_can_be_deleted_and_takes_its_detail_with_it(api_as):
    event = make_event()

    assert api_as(event.creator).delete(detail(event)).status_code == 204
    assert not EventDetail.objects.exists()


# --- Alongside jobs ---------------------------------------------------------------------


def test_events_and_jobs_share_the_feed_and_can_be_told_apart(api, django_assert_max_num_queries):
    make_job(status="PUBLISHED", title="Backend Engineer")
    make_event(status="PUBLISHED", title="Kochi Python Meetup")
    make_event(status="PUBLISHED", title="Remote Rust Night", event={"format": "ONLINE"})
    make_event(title="A draft meetup")

    everything = api.get(URL).json()["results"]
    assert {row["type"] for row in everything} == {"JOB", "EVENT"}
    assert len(everything) == 3

    events = api.get(URL, {"type": "EVENT"}).json()["results"]
    assert {row["title"] for row in events} == {"Kochi Python Meetup", "Remote Rust Night"}
    assert all(row["job"] is None and row["event"]["start_at"] for row in events)
    jobs = api.get(URL, {"type": "JOB"}).json()["results"]
    assert [(row["title"], row["event"]) for row in jobs] == [("Backend Engineer", None)]

    # Filters meant for one type simply leave the other out.
    remote = api.get(URL, {"work_mode": "REMOTE", "type": "EVENT"}).json()["results"]
    assert [row["title"] for row in remote] == ["Remote Rust Night"]
    assert api.get(URL, {"type": "EVENT", "employment_type": "FULL_TIME"}).json()["results"] == []
    found = api.get(URL, {"q": "meetup"}).json()["results"]
    assert [row["title"] for row in found] == ["Kochi Python Meetup"]

    for _ in range(5):
        make_event(status="PUBLISHED")
    with django_assert_max_num_queries(4):
        assert len(api.get(URL).json()["results"]) == 8


def test_an_event_takes_no_applications_or_referrals(api_as):
    event = make_event(status="PUBLISHED")
    visitor, manager = api_as(UserFactory()), api_as(event.creator)

    viewer = visitor.get(detail(event)).json()["viewer"]
    assert (viewer["can_apply"], viewer["application"], viewer["can_request_referral"]) == (
        False,
        None,
        False,
    )
    assert (
        visitor.post(f"/api/v1/jobs/{event.pk}/apply/", {}, format="multipart").status_code == 404
    )
    assert manager.get(f"/api/v1/jobs/{event.pk}/applications/").status_code == 404
    assert manager.get(f"/api/v1/jobs/{event.pk}/applications/summary/").status_code == 404


def test_an_event_past_its_registration_deadline_is_not_expired_like_a_job():
    from opportunities import services

    event = make_event(status="PUBLISHED")
    Opportunity.objects.filter(pk=event.pk).update(deadline=timezone.now() - timedelta(hours=1))

    assert services.expire_due() == 0
    event.refresh_from_db()
    assert event.status == "PUBLISHED"
