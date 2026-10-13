from datetime import timedelta

import pytest
from django.core import mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import AuditLog
from common.throttles import ScopedThrottle
from events import tasks
from events.models import EventDetail, EventRegistration
from events.tests.factories import add_registration, make_event
from notifications.models import Notification
from opportunities.models import Opportunity
from opportunities.tests.factories import make_job
from organizations.tests.factories import organization_with_roles
from users.models import UserBlock
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def url(event, action) -> str:
    return f"/api/v1/events/{event.pk}/{action}/"


def detail(event) -> str:
    return f"/api/v1/opportunities/{event.pk}/"


def ahead(**delta):
    return timezone.now() + timedelta(**delta)


def ago(**delta):
    return timezone.now() - timedelta(**delta)


def open_event(capacity=None, **fields):
    event = fields.pop("event", {})
    return make_event(status="PUBLISHED", event={"capacity": capacity, **event}, **fields)


def places(event) -> tuple[int, list[str]]:
    """The stored count, and every registration's status in sign-up order."""
    stored = EventDetail.objects.get(pk=event.pk).confirmed_count
    statuses = EventRegistration.objects.filter(event_id=event.pk).order_by("created_at", "id")
    return stored, [r.status for r in statuses]


# --- Registering ------------------------------------------------------------------------


def test_registering_takes_a_place(api_as):
    event, user = open_event(capacity=2), UserFactory()
    client = api_as(user)

    response = client.post(url(event, "register"))

    assert response.status_code == 201
    body = response.json()
    assert (body["status"], body["waitlist_position"]) == ("CONFIRMED", None)
    assert places(event) == (1, ["CONFIRMED"])
    log = AuditLog.objects.get(action="event.registered")
    assert (log.actor, log.metadata["status"]) == (user, "CONFIRMED")

    # Registering again changes nothing and is not an error.
    again = client.post(url(event, "register"))
    assert (again.status_code, again.json()["id"]) == (200, body["id"])
    assert places(event) == (1, ["CONFIRMED"])
    assert AuditLog.objects.filter(action="event.registered").count() == 1
    assert client.get(url(event, "my-registration")).json()["status"] == "CONFIRMED"


def test_a_full_event_puts_people_on_the_waitlist_in_order(api_as):
    event = open_event(capacity=1)
    add_registration(event)
    first, second = UserFactory(), UserFactory()

    one = api_as(first).post(url(event, "register"))
    two = api_as(second).post(url(event, "register"))

    assert (one.status_code, one.json()["status"], one.json()["waitlist_position"]) == (
        201,
        "WAITLISTED",
        1,
    )
    assert (two.json()["status"], two.json()["waitlist_position"]) == ("WAITLISTED", 2)
    assert places(event) == (1, ["CONFIRMED", "WAITLISTED", "WAITLISTED"])


def test_an_event_without_a_limit_never_waitlists(api_as):
    event = open_event(capacity=None)

    statuses = [
        api_as(UserFactory()).post(url(event, "register")).json()["status"] for _ in range(5)
    ]

    assert statuses == ["CONFIRMED"] * 5
    assert places(event)[0] == 5


def test_the_event_page_tells_each_viewer_how_they_stand(api, api_as):
    link = "https://meet.example.com/room"
    event = open_event(capacity=1, event={"format": "HYBRID", "online_url": link})
    going, waiting, stranger = UserFactory(), UserFactory(), UserFactory()

    def viewer(client):
        body = client.get(detail(event)).json()
        return body["viewer"]["can_register"], body["viewer"]["registration"], body["event"]

    assert viewer(api)[:2] == (False, None)
    assert viewer(api_as(stranger))[:2] == (True, None)
    api_as(going).post(url(event, "register"))
    api_as(waiting).post(url(event, "register"))

    can, registration, shown = viewer(api_as(going))
    assert (can, registration["status"], registration["waitlist_position"]) == (
        False,
        "CONFIRMED",
        None,
    )
    # Holding a place is what gets you the way in.
    assert (shown["online_url"], shown["confirmed_count"]) == (link, 1)
    can, registration, shown = viewer(api_as(waiting))
    assert (can, registration["status"], registration["waitlist_position"]) == (
        False,
        "WAITLISTED",
        1,
    )
    assert shown["online_url"] == ""
    assert viewer(api_as(stranger))[2]["online_url"] == ""

    # After cancelling, the registration is still reported, and they may register again.
    api_as(going).post(url(event, "cancel-registration"))
    can, registration, shown = viewer(api_as(going))
    assert (can, registration["status"], shown["online_url"]) == (True, "CANCELLED", "")


@pytest.mark.parametrize(
    ("event", "fields"),
    [
        ({"event_status": "REGISTRATION_CLOSED"}, {}),
        ({"event_status": "SCHEDULED", "registration_opens_at": ahead(days=1)}, {}),
        ({"event_status": "SCHEDULED", "registration_opens_at": None}, {}),
        ({}, {"deadline": ago(minutes=1)}),
        ({"start_at": ago(minutes=5), "end_at": ahead(hours=1)}, {}),
        ({}, {"moderation_status": "HIDDEN"}),
    ],
)
def test_registration_that_is_not_open_is_refused(api_as, event, fields):
    hosted = make_event(status="PUBLISHED", event=event, **fields)
    # The host can always see their own event, even hidden, so the answer is about
    # registration and not about visibility.
    response = api_as(hosted.creator).post(url(hosted, "register"))

    assert (response.status_code, response.json()["code"]) == (409, "registration_closed")
    assert not EventRegistration.objects.exists()


def test_the_times_decide_even_if_the_sweep_is_late(api_as):
    opened = make_event(
        status="PUBLISHED",
        event={"event_status": "SCHEDULED", "registration_opens_at": ago(minutes=1)},
    )

    assert api_as(UserFactory()).post(url(opened, "register")).status_code == 201


def test_cancelled_and_completed_events_take_no_registrations(api_as):
    cancelled = make_event(status="CLOSED")
    completed = make_event(status="CLOSED", close_reason="COMPLETED")

    for event in (cancelled, completed):
        response = api_as(UserFactory()).post(url(event, "register"))
        assert (response.status_code, response.json()["code"]) == (409, "registration_closed")


def test_who_cannot_register_at_all(api, api_as):
    event, draft, job = open_event(), make_event(), make_job(status="PUBLISHED")
    organization, _ = organization_with_roles()
    private = open_event(organization=organization, visibility="ORGANIZATION")

    assert api.post(url(event, "register")).status_code == 401
    unverified = api_as(UserFactory(unverified=True)).post(url(event, "register"))
    assert (unverified.status_code, unverified.json()["code"]) == (403, "email_not_verified")
    client = api_as(UserFactory())
    for hidden in (draft, job, private):
        assert client.post(url(hidden, "register")).status_code == 404
        assert client.get(url(hidden, "my-registration")).status_code == 404
    assert client.get(url(event, "my-registration")).status_code == 404  # never registered
    assert not EventRegistration.objects.exists()


def test_a_block_on_a_personal_event_reads_as_closed(api_as):
    event, blocked = open_event(), UserFactory()
    UserBlock.objects.create(blocker=event.creator, blocked=blocked)

    response = api_as(blocked).post(url(event, "register"))

    assert (response.status_code, response.json()["code"]) == (409, "registration_closed")
    assert api_as(blocked).get(detail(event)).json()["viewer"]["can_register"] is False


def test_registering_is_rate_limited(api_as, monkeypatch):
    monkeypatch.setitem(ScopedThrottle.THROTTLE_RATES, "event_register", "2/hour")
    client = api_as(UserFactory())

    codes = [client.post(url(open_event(), "register")).status_code for _ in range(3)]

    assert codes == [201, 201, 429]


# --- Cancelling and the waitlist --------------------------------------------------------


def test_cancelling_gives_the_place_to_whoever_waited_longest(
    api_as, django_capture_on_commit_callbacks
):
    event = open_event(capacity=1, title="Kochi Python Meetup")
    going = add_registration(event)
    first = add_registration(event, status="WAITLISTED")
    second = add_registration(event, status="WAITLISTED")

    with django_capture_on_commit_callbacks(execute=True):
        response = api_as(going.user).post(url(event, "cancel-registration"))

    assert (response.status_code, response.json()["status"]) == (200, "CANCELLED")
    assert places(event) == (1, ["CANCELLED", "CONFIRMED", "WAITLISTED"])
    first.refresh_from_db()
    assert (first.status, first.waitlisted_at) == ("CONFIRMED", None)
    # The one who got the place is told, in the app and by email; nobody else is.
    notice = Notification.objects.get()
    assert (notice.recipient, notice.type) == (first.user, "REGISTRATION_PROMOTED")
    assert [m.to for m in mail.outbox] == [[first.user.email]]
    assert "Kochi Python Meetup" in mail.outbox[0].subject
    assert api_as(second.user).get(url(event, "my-registration")).json()["waitlist_position"] == 1
    assert AuditLog.objects.filter(action="event.registration_promoted").count() == 1
    log = AuditLog.objects.get(action="event.registration_cancelled")
    assert log.metadata["from"] == "CONFIRMED" and log.metadata["by"] == "registrant"

    # Cancelling twice changes nothing.
    assert api_as(going.user).post(url(event, "cancel-registration")).status_code == 200
    assert places(event) == (1, ["CANCELLED", "CONFIRMED", "WAITLISTED"])
    assert Notification.objects.count() == 1


def test_leaving_the_waitlist_frees_no_place_and_moves_the_queue_up(api_as):
    event = open_event(capacity=1)
    add_registration(event)
    first = add_registration(event, status="WAITLISTED")
    second = add_registration(event, status="WAITLISTED")

    api_as(first.user).post(url(event, "cancel-registration"))

    assert places(event) == (1, ["CONFIRMED", "CANCELLED", "WAITLISTED"])
    assert not Notification.objects.exists()
    assert api_as(second.user).get(url(event, "my-registration")).json()["waitlist_position"] == 1


def test_coming_back_after_cancelling_reuses_the_row_at_the_back_of_the_queue(api_as):
    event = open_event(capacity=1)
    returning = add_registration(event)
    waiting = add_registration(event, status="WAITLISTED")
    client = api_as(returning.user)
    client.post(url(event, "cancel-registration"))  # the place goes to the one waiting

    response = client.post(url(event, "register"))

    assert response.status_code == 201
    assert (response.json()["id"], response.json()["status"]) == (
        str(returning.pk),
        "WAITLISTED",
    )
    assert response.json()["waitlist_position"] == 1
    assert EventRegistration.objects.count() == 2
    waiting.refresh_from_db()
    assert waiting.status == "CONFIRMED"
    assert places(event)[0] == 1


def test_a_registration_cannot_be_cancelled_once_the_event_has_started(api_as):
    event = open_event()
    registration = add_registration(event)
    EventDetail.objects.filter(pk=event.pk).update(start_at=ago(minutes=1))

    response = api_as(registration.user).post(url(event, "cancel-registration"))

    assert (response.status_code, response.json()["code"]) == (409, "event_started")
    assert api_as(UserFactory()).post(url(event, "cancel-registration")).status_code == 404
    assert places(event) == (1, ["CONFIRMED"])


# --- Organizers -------------------------------------------------------------------------


def test_organizers_see_everyone_who_registered(api_as, django_assert_max_num_queries):
    organization, members = organization_with_roles("RECRUITER", "MEMBER")
    event = open_event(capacity=2, organization=organization, creator=members["OWNER"].user)
    going = [add_registration(event) for _ in range(2)]
    waiting = add_registration(event, status="WAITLISTED")
    add_registration(event, status="CANCELLED")
    client = api_as(members["RECRUITER"].user)

    everyone = client.get(url(event, "registrations")).json()["results"]
    assert [row["status"] for row in everyone] == [
        "CONFIRMED",
        "CONFIRMED",
        "WAITLISTED",
        "CANCELLED",
    ]
    assert everyone[0]["person"]["id"] == str(going[0].user.pk)
    assert set(everyone[0]) == {
        "id",
        "status",
        "person",
        "waitlisted_at",
        "checked_in_at",
        "created_at",
    }
    queue = client.get(url(event, "registrations"), {"status": "WAITLISTED"}).json()["results"]
    assert [row["id"] for row in queue] == [str(waiting.pk)]
    assert client.get(url(event, "registrations"), {"status": "nope"}).status_code == 400
    assert client.get(url(event, "registrations/summary")).json() == {
        "counts": {"CONFIRMED": 2, "WAITLISTED": 1, "CANCELLED": 1},
        "capacity": 2,
        "checked_in": 0,
        # The event is a week away, so nobody can be checked in yet.
        "checkin_open": False,
    }

    for _ in range(6):
        add_registration(event, status="WAITLISTED")
    with django_assert_max_num_queries(6):
        assert len(client.get(url(event, "registrations")).json()["results"]) == 10

    # Not for the organization's ordinary members, attendees or strangers.
    for outsider in (members["MEMBER"].user, going[0].user, UserFactory()):
        assert api_as(outsider).get(url(event, "registrations")).status_code == 403
        assert api_as(outsider).get(url(event, "registrations/summary")).status_code == 403


def test_an_organizer_can_cancel_someones_registration(api_as):
    event = open_event(capacity=1)
    going = add_registration(event)
    waiting = add_registration(event, status="WAITLISTED")
    remove = f"/api/v1/events/{event.pk}/registrations/{going.pk}/remove/"

    assert api_as(waiting.user).post(remove).status_code == 403
    response = api_as(event.creator).post(remove)

    assert (response.status_code, response.json()["status"]) == (200, "CANCELLED")
    assert places(event) == (1, ["CANCELLED", "CONFIRMED"])
    told = {(n.recipient, n.type) for n in Notification.objects.all()}
    assert told == {
        (going.user, "REGISTRATION_REMOVED"),
        (waiting.user, "REGISTRATION_PROMOTED"),
    }
    # No name and no reason: the organizers decided, that is all the person is told.
    assert Notification.objects.get(type="REGISTRATION_REMOVED").actor is None
    log = AuditLog.objects.get(action="event.registration_cancelled")
    assert (log.actor, log.metadata["by"]) == (event.creator, "organizer")

    # Again changes nothing; a registration of another event is not found here.
    assert api_as(event.creator).post(remove).status_code == 200
    assert Notification.objects.count() == 2
    elsewhere = add_registration(open_event(creator=event.creator))
    assert (
        api_as(event.creator)
        .post(f"/api/v1/events/{event.pk}/registrations/{elsewhere.pk}/remove/")
        .status_code
        == 404
    )


def test_changing_the_number_of_places_after_publishing(api_as):
    event = open_event(capacity=2)
    add_registration(event)
    add_registration(event)
    queue = [add_registration(event, status="WAITLISTED") for _ in range(3)]
    client = api_as(event.creator)

    def set_capacity(value):
        return client.patch(detail(event), {"event": {"capacity": value}})

    # Nobody loses a place by the number being lowered.
    shrunk = set_capacity(1)
    assert (shrunk.status_code, shrunk.json()["code"]) == (422, "capacity_below_confirmed")
    assert list(shrunk.json()["errors"]) == ["event.capacity"]
    assert places(event)[0] == 2

    # One more place: the head of the queue gets it.
    grown = set_capacity(3)
    assert grown.status_code == 200
    assert (grown.json()["event"]["capacity"], grown.json()["event"]["confirmed_count"]) == (3, 3)
    in_queue_order = EventRegistration.objects.filter(pk__in=[q.pk for q in queue]).order_by(
        "created_at", "id"
    )
    assert [r.status for r in in_queue_order] == [
        "CONFIRMED",
        "WAITLISTED",
        "WAITLISTED",
    ]
    assert Notification.objects.get().recipient == queue[0].user

    # No limit: everyone waiting gets in.
    assert set_capacity(None).status_code == 200
    assert places(event) == (5, ["CONFIRMED"] * 5)
    assert Notification.objects.filter(type="REGISTRATION_PROMOTED").count() == 3


def test_closing_and_reopening_registration_by_hand(api_as):
    event = open_event()
    host, guest = api_as(event.creator), api_as(UserFactory())
    kept = add_registration(event)

    assert api_as(UserFactory()).post(url(event, "close-registration")).status_code == 403
    assert host.post(url(event, "close-registration")).status_code == 204
    assert host.post(url(event, "close-registration")).status_code == 204  # already closed

    assert guest.post(url(event, "register")).json()["code"] == "registration_closed"
    kept.refresh_from_db()
    assert kept.status == "CONFIRMED"  # people already in stay in
    assert AuditLog.objects.filter(action="event.registration_closed").count() == 1

    assert host.post(url(event, "open-registration")).status_code == 204
    assert guest.post(url(event, "register")).status_code == 201

    # Not once the deadline has passed, and never for something that is not an open event.
    host.post(url(event, "close-registration"))
    Opportunity.objects.filter(pk=event.pk).update(deadline=ago(minutes=1))
    late = host.post(url(event, "open-registration"))
    assert (late.status_code, late.json()["code"]) == (409, "deadline_passed")
    job = make_job(status="PUBLISHED")
    assert api_as(job.creator).post(url(job, "close-registration")).status_code == 404
    draft = make_event()
    refused = api_as(draft.creator).post(url(draft, "open-registration"))
    assert (refused.status_code, refused.json()["code"]) == (409, "event_not_published")


# --- When the event is cancelled --------------------------------------------------------


def test_cancelling_an_event_tells_everyone_registered_once(
    api_as, django_capture_on_commit_callbacks
):
    event = open_event(capacity=1, title="Kochi Python Meetup")
    going = add_registration(event)
    waiting = add_registration(event, status="WAITLISTED")
    left = add_registration(event, status="CANCELLED")

    with django_capture_on_commit_callbacks(execute=True):
        response = api_as(event.creator).post(detail(event) + "close/", {"reason": "CANCELLED"})

    assert response.status_code == 200
    told = Notification.objects.filter(type="EVENT_CANCELLED")
    assert {n.recipient for n in told} == {going.user, waiting.user}
    assert left.user not in {n.recipient for n in Notification.objects.all()}
    assert sorted(m.to[0] for m in mail.outbox) == sorted([going.user.email, waiting.user.email])
    # The registrations stay as the record of who was coming.
    assert places(event) == (1, ["CONFIRMED", "WAITLISTED", "CANCELLED"])

    # A retried task tells nobody twice.
    assert tasks.announce_cancellation(str(event.pk)) == 0
    assert Notification.objects.filter(type="EVENT_CANCELLED").count() == 2

    # Nobody new gets in, and leaving no longer promotes anyone.
    assert api_as(UserFactory()).post(url(event, "register")).status_code == 409
    api_as(going.user).post(url(event, "cancel-registration"))
    waiting.refresh_from_db()
    assert waiting.status == "WAITLISTED"


# --- Who is going -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("visibility", "expected"),
    [
        # (visitor, stranger, on the waitlist, going, organizer)
        ("PUBLIC", (200, 200, 200, 200, 200)),
        ("ATTENDEES", (403, 403, 403, 200, 200)),
        ("HIDDEN", (403, 403, 403, 403, 200)),
    ],
)
def test_the_attendee_list_is_shown_as_the_organizer_chose(api, api_as, visibility, expected):
    event = open_event(capacity=1, event={"attendee_visibility": visibility})
    going = add_registration(event)
    waiting = add_registration(event, status="WAITLISTED")
    clients = (
        api,
        api_as(UserFactory()),
        api_as(waiting.user),
        api_as(going.user),
        api_as(event.creator),
    )

    responses = [client.get(url(event, "attendees")) for client in clients]

    assert tuple(r.status_code for r in responses) == expected
    # Only people holding a place are listed, as public cards.
    listed = responses[-1].json()
    assert [person["id"] for person in listed] == [str(going.user.pk)]
    assert set(listed[0]) == {"id", "display_name", "headline", "avatar_url"}


def test_the_attendee_list_leaves_out_blocked_people_and_hidden_events(api_as):
    event = open_event(event={"attendee_visibility": "PUBLIC"})
    seen, blocker, blocked = (add_registration(event).user for _ in range(3))
    viewer = UserFactory()
    UserBlock.objects.create(blocker=blocker, blocked=viewer)
    UserBlock.objects.create(blocker=viewer, blocked=blocked)

    listed = api_as(viewer).get(url(event, "attendees")).json()

    assert [person["id"] for person in listed] == [str(seen.pk)]
    assert api_as(viewer).get(url(make_event(), "attendees")).status_code == 404


# --- My events --------------------------------------------------------------------------


def test_my_events_lists_what_i_am_going_to_or_waiting_for_soonest_first(api, api_as):
    me = UserFactory()
    later = open_event(title="Later", event={"start_at": ahead(days=9), "end_at": ahead(days=10)})
    sooner = open_event(title="Sooner", capacity=1)
    add_registration(later, me)
    add_registration(sooner)
    add_registration(sooner, me, status="WAITLISTED")
    add_registration(open_event(title="Left"), me, status="CANCELLED")
    add_registration(open_event(title="Someone else's"))

    rows = api_as(me).get("/api/v1/users/me/event-registrations/").json()

    assert [(row["event"]["title"], row["status"]) for row in rows] == [
        ("Sooner", "WAITLISTED"),
        ("Later", "CONFIRMED"),
    ]
    assert rows[0]["event"]["id"] == str(sooner.pk)
    assert rows[0]["event"]["timezone"] == "Asia/Kolkata"
    assert api.get("/api/v1/users/me/event-registrations/").status_code == 401


# --- The database's own rules -----------------------------------------------------------


def test_the_database_refuses_what_the_service_never_does():
    event = open_event(capacity=1)
    registration = add_registration(event)

    with pytest.raises(IntegrityError), transaction.atomic():
        EventDetail.objects.filter(pk=event.pk).update(confirmed_count=2)  # overbooked
    with pytest.raises(IntegrityError), transaction.atomic():
        add_registration(event, registration.user, status="WAITLISTED")  # twice
    with pytest.raises(IntegrityError), transaction.atomic():
        EventRegistration.objects.create(
            event_id=event.pk, user=UserFactory(), status="WAITLISTED"
        )  # waiting, but with no place in the queue
    with pytest.raises(IntegrityError), transaction.atomic():
        EventRegistration.objects.filter(pk=registration.pk).update(
            waitlisted_at=timezone.now()
        )  # going, but still in the queue
