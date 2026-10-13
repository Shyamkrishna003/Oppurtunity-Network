import threading
from contextlib import contextmanager
from datetime import timedelta
from unittest import mock

import pytest
from django.core import signing
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from audit.models import AuditLog
from common.throttles import ScopedThrottle
from events import checkin
from events.models import EventRegistration
from events.tests.factories import add_registration, make_event
from organizations.tests.factories import organization_with_roles
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def url(event, action) -> str:
    return f"/api/v1/events/{event.pk}/{action}/"


def ahead(**delta):
    return timezone.now() + timedelta(**delta)


def ago(**delta):
    return timezone.now() - timedelta(**delta)


@contextmanager
def freeze_later(**delta):
    """Run a block as if this much time had passed."""
    later = timezone.now() + timedelta(**delta)
    with mock.patch("time.time", return_value=later.timestamp()):
        yield


def doors_open(**fields):
    """A published event that starts in an hour: inside the check-in window."""
    event = fields.pop("event", {})
    times = {"start_at": ahead(hours=1), "end_at": ahead(hours=3)}
    return make_event(status="PUBLISHED", event={**times, **event}, **fields)


def scan(client, event, code):
    return client.post(url(event, "check-in"), {"code": code})


# --- The attendee's code ----------------------------------------------------------------


def test_someone_holding_a_place_gets_a_code_and_nobody_else_does(api_as):
    event = doors_open(event={"capacity": 1})
    going = add_registration(event)
    waiting = add_registration(event, status="WAITLISTED")
    left = add_registration(event, status="CANCELLED")

    mine = api_as(going.user).get(url(event, "my-registration")).json()

    assert mine["checkin_code"] == checkin.code_for(going)
    # The same code whenever it is asked for, so a saved or printed one keeps working.
    with freeze_later(seconds=90):
        assert (
            api_as(going.user).get(url(event, "my-registration")).json()["checkin_code"]
            == (mine["checkin_code"])
        )
    assert mine["checked_in_at"] is None
    # Nothing in it can be read off as the person or the event.
    assert str(going.user.pk) not in mine["checkin_code"]
    assert str(event.pk) not in mine["checkin_code"]
    for other in (waiting, left):
        assert api_as(other.user).get(url(event, "my-registration")).json()["checkin_code"] is None


def test_no_code_for_an_event_that_is_cancelled_or_over(api_as):
    cancelled = make_event(status="CLOSED")
    completed = make_event(status="CLOSED", close_reason="COMPLETED")

    for event in (cancelled, completed):
        going = add_registration(event)
        mine = api_as(going.user).get(url(event, "my-registration")).json()
        assert (mine["status"], mine["checkin_code"]) == ("CONFIRMED", None)


# --- At the door ------------------------------------------------------------------------


def test_an_organizer_checks_someone_in_from_their_code(api_as):
    event = doors_open()
    going = add_registration(event)
    add_registration(event)
    host = api_as(event.creator)
    code = api_as(going.user).get(url(event, "my-registration")).json()["checkin_code"]

    response = scan(host, event, code)

    assert response.status_code == 200
    body = response.json()
    assert body["person"]["id"] == str(going.user.pk)
    going.refresh_from_db()
    assert going.checked_in_at is not None and going.checked_in_by == event.creator
    assert body["checked_in_at"].startswith(going.checked_in_at.isoformat()[:19])
    log = AuditLog.objects.get(action="event.checked_in")
    assert (log.actor, log.target_id) == (event.creator, going.pk)

    # The attendee and the organizers both see it.
    assert api_as(going.user).get(url(event, "my-registration")).json()["checked_in_at"]
    summary = host.get(url(event, "registrations/summary")).json()
    assert (summary["checked_in"], summary["checkin_open"]) == (1, True)
    rows = host.get(url(event, "registrations")).json()["results"]
    assert [bool(row["checked_in_at"]) for row in rows] == [True, False]


def test_a_code_checks_in_exactly_once(api_as):
    event = doors_open()
    going = add_registration(event)
    host, code = api_as(event.creator), checkin.code_for(going)
    first = scan(host, event, code)

    second = scan(host, event, code)

    assert (second.status_code, second.json()["code"]) == (409, "already_checked_in")
    # It says when the first scan was, and that time has not moved.
    going.refresh_from_db()
    assert second.json()["errors"]["checked_in_at"] == [going.checked_in_at.isoformat()]
    assert first.json()["checked_in_at"][:19] == going.checked_in_at.isoformat()[:19]
    assert AuditLog.objects.filter(action="event.checked_in").count() == 1


def test_codes_that_are_not_genuine_are_all_refused_the_same_way(api_as):
    event, elsewhere = doors_open(), doors_open()
    going = add_registration(event)
    other_event_code = checkin.code_for(add_registration(elsewhere))
    genuine = checkin.code_for(going)
    host = api_as(event.creator)
    made_up = signing.Signer(salt="some.other.salt").sign_object([str(going.pk), 0])
    timestamped = signing.dumps([str(going.pk), 0], salt="events.checkin", compress=False)
    unsigned = f"{going.pk}:0"

    for code in (
        "nonsense",
        genuine[:-2] + "xx",  # altered signature
        "x" + genuine,  # altered payload
        made_up,  # signed for something else
        timestamped,  # signed with our secret, but not in the form a code takes
        unsigned,
        other_event_code,  # genuine, but for another event
        "a" * 300,
    ):
        response = scan(host, event, code)
        assert (response.status_code, response.json()["code"]) == (422, "invalid_code"), code

    assert scan(host, event, "").status_code == 400
    assert scan(host, event, "a" * 301).status_code == 400
    assert not EventRegistration.objects.filter(checked_in_at__isnull=False).exists()


def test_a_code_from_an_earlier_stay_stops_working(api_as):
    event = doors_open()
    going = add_registration(event)
    guest, host = api_as(going.user), api_as(event.creator)
    old = guest.get(url(event, "my-registration")).json()["checkin_code"]

    guest.post(url(event, "cancel-registration"))
    cancelled = scan(host, event, old)
    assert (cancelled.status_code, cancelled.json()["code"]) == (422, "not_registered")

    new = guest.post(url(event, "register")).json()["checkin_code"]
    assert new != old
    assert scan(host, event, old).json()["code"] == "invalid_code"
    assert scan(host, event, new).status_code == 200


def test_being_promoted_from_the_waitlist_gives_a_working_code(api_as):
    event = doors_open(event={"capacity": 1})
    going = add_registration(event)
    waiting = add_registration(event, status="WAITLISTED")
    host = api_as(event.creator)
    # Even a code made for them while waiting must not get them in.
    premature = checkin.code_for(waiting)
    assert scan(host, event, premature).json()["code"] == "not_registered"

    api_as(going.user).post(url(event, "cancel-registration"))

    code = api_as(waiting.user).get(url(event, "my-registration")).json()["checkin_code"]
    assert code != premature
    assert scan(host, event, premature).json()["code"] == "invalid_code"
    assert scan(host, event, code).status_code == 200


@pytest.mark.parametrize(
    ("times", "expected"),
    [
        ({"start_at": ahead(hours=3), "end_at": ahead(hours=5)}, 422),  # too early
        ({"start_at": ahead(hours=1, minutes=59), "end_at": ahead(hours=5)}, 200),
        ({"start_at": ago(hours=1), "end_at": ahead(minutes=5)}, 200),  # under way
        ({"start_at": ago(hours=3), "end_at": ago(minutes=1)}, 422),  # over
    ],
)
def test_check_in_is_open_from_two_hours_before_the_start_until_the_end(api_as, times, expected):
    event = make_event(status="PUBLISHED", event=times)
    going = add_registration(event)

    response = scan(api_as(event.creator), event, checkin.code_for(going))

    assert response.status_code == expected
    if expected == 422:
        assert response.json()["code"] == "checkin_closed"
    summary = api_as(event.creator).get(url(event, "registrations/summary")).json()
    assert summary["checkin_open"] is (expected == 200)


def test_a_cancelled_event_checks_nobody_in(api_as):
    event = make_event(
        status="CLOSED", event={"start_at": ahead(hours=1), "end_at": ahead(hours=2)}
    )
    going = add_registration(event)

    response = scan(api_as(event.creator), event, checkin.code_for(going))

    assert (response.status_code, response.json()["code"]) == (422, "checkin_closed")


def test_only_the_people_running_the_event_can_check_anyone_in(api, api_as):
    organization, members = organization_with_roles("RECRUITER", "MEMBER")
    event = doors_open(organization=organization, creator=members["OWNER"].user)
    going = add_registration(event)
    code = checkin.code_for(going)

    assert scan(api, event, code).status_code == 401
    # Not the attendee themselves, with their own genuine code.
    for outsider in (going.user, members["MEMBER"].user, UserFactory()):
        assert scan(api_as(outsider), event, code).status_code == 403
    going.refresh_from_db()
    assert going.checked_in_at is None

    assert scan(api_as(members["RECRUITER"].user), event, code).status_code == 200


def test_nothing_accepts_a_checked_in_flag_from_a_client(api_as):
    event = doors_open()
    guest = UserFactory()
    client = api_as(guest)
    claim = {"checked_in": True, "checked_in_at": timezone.now().isoformat(), "status": "CONFIRMED"}

    client.post(url(event, "register"), claim)
    client.post(url(event, "check-in"), claim)
    client.patch(f"/api/v1/opportunities/{event.pk}/", {"event": claim})

    registration = EventRegistration.objects.get(user=guest)
    assert registration.checked_in_at is None


def test_someone_checked_in_keeps_their_registration(api_as):
    event = doors_open(event={"capacity": 1})
    going = add_registration(event)
    waiting = add_registration(event, status="WAITLISTED")
    host = api_as(event.creator)
    scan(host, event, checkin.code_for(going))

    left = api_as(going.user).post(url(event, "cancel-registration"))
    removed = host.post(f"/api/v1/events/{event.pk}/registrations/{going.pk}/remove/")

    for response in (left, removed):
        assert (response.status_code, response.json()["code"]) == (409, "already_checked_in")
    going.refresh_from_db()
    waiting.refresh_from_db()
    assert (going.status, waiting.status) == ("CONFIRMED", "WAITLISTED")


def test_check_in_is_rate_limited(api_as, monkeypatch):
    monkeypatch.setitem(ScopedThrottle.THROTTLE_RATES, "event_checkin", "2/hour")
    event = doors_open()
    host = api_as(event.creator)

    codes = [scan(host, event, "nonsense").status_code for _ in range(3)]

    assert codes == [422, 422, 429]


def test_the_database_only_lets_someone_with_a_place_be_checked_in():
    event = doors_open()
    waiting = add_registration(event, status="WAITLISTED")

    with pytest.raises(IntegrityError), transaction.atomic():
        EventRegistration.objects.filter(pk=waiting.pk).update(checked_in_at=timezone.now())


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_two_devices_scanning_the_same_code_at_once_check_in_once():
    event = doors_open()
    going = add_registration(event)
    code = checkin.code_for(going)
    barrier = threading.Barrier(4)
    outcomes = []

    def run():
        barrier.wait()
        try:
            outcomes.append(
                checkin.check_in(actor=event.creator, opportunity_id=event.pk, code=code).newly
            )
        except Exception as exc:
            outcomes.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert sorted(outcomes) == [False, False, False, True]
    assert AuditLog.objects.filter(action="event.checked_in").count() == 1
