from datetime import UTC, datetime, timedelta

import pytest
from django.core import mail
from django.utils import timezone

from events import reminders, tasks
from events.models import EventDetail
from events.tests.factories import add_registration, make_event
from notifications import services as notifications
from notifications.models import Category, Notification
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def starting_in(**delta):
    start = timezone.now() + timedelta(**delta)
    return {"start_at": start, "end_at": start + timedelta(hours=2)}


def reminded() -> list[tuple[str, str]]:
    notices = Notification.objects.filter(type="EVENT_REMINDER").order_by("created_at", "id")
    return [(n.recipient.email, n.payload["lead"]) for n in notices]


def test_the_people_going_are_reminded_the_day_before(api_as, django_capture_on_commit_callbacks):
    event = make_event(
        status="PUBLISHED",
        title="Kochi Python Meetup",
        event={
            "start_at": datetime(2030, 5, 3, 12, 30, tzinfo=UTC),
            "end_at": datetime(2030, 5, 3, 14, 30, tzinfo=UTC),
            "capacity": 2,
        },
    )
    EventDetail.objects.filter(pk=event.pk).update(**starting_in(hours=20))
    going = [add_registration(event).user for _ in range(2)]
    add_registration(event, status="WAITLISTED")
    add_registration(event, status="CANCELLED")

    with django_capture_on_commit_callbacks(execute=True):
        sent = tasks.send_reminders()

    assert sent == {"24h": 2, "1h": 0}
    assert sorted(reminded()) == sorted((user.email, "24h") for user in going)
    assert sorted(m.to[0] for m in mail.outbox) == sorted(user.email for user in going)
    assert mail.outbox[0].subject.endswith("“Kochi Python Meetup” is tomorrow")
    listed = api_as(going[0]).get("/api/v1/notifications/").json()["results"][0]
    assert listed["url"] == f"/opportunities/{event.pk}"
    assert "Kerala Startup Mission" in listed["body"]
    assert EventDetail.objects.get(pk=event.pk).reminder_24h_sent_at is not None

    # Running it again reminds nobody twice.
    assert tasks.send_reminders() == {"24h": 0, "1h": 0}
    assert len(reminded()) == 2


def test_the_time_is_given_as_a_clock_at_the_event_reads():
    event = make_event(
        event={
            "start_at": datetime(2030, 5, 3, 12, 30, tzinfo=UTC),
            "end_at": datetime(2030, 5, 3, 14, 30, tzinfo=UTC),
            "timezone": "Asia/Kolkata",
        }
    )
    assert reminders.starts_text(event.event) == "Fri 3 May, 18:00"

    EventDetail.objects.filter(pk=event.pk).update(timezone="America/New_York")
    assert reminders.starts_text(EventDetail.objects.get(pk=event.pk)) == "Fri 3 May, 08:30"
    EventDetail.objects.filter(pk=event.pk).update(timezone="Not/AZone")
    assert reminders.starts_text(EventDetail.objects.get(pk=event.pk)) == "Fri 3 May, 12:30"


def test_an_hour_before_there_is_a_second_reminder(api_as):
    event = make_event(status="PUBLISHED", event=starting_in(hours=20))
    user = add_registration(event).user
    reminders.send_due()

    EventDetail.objects.filter(pk=event.pk).update(**starting_in(minutes=40))
    sent = reminders.send_due()

    assert sent == {"24h": 0, "1h": 1}
    assert reminded() == [(user.email, "24h"), (user.email, "1h")]
    titles = [n["title"] for n in api_as(user).get("/api/v1/notifications/").json()["results"]]
    assert titles[0].endswith("starts in about an hour")
    assert reminders.send_due() == {"24h": 0, "1h": 0}


def test_an_event_less_than_an_hour_away_gets_only_the_hour_reminder():
    event = make_event(status="PUBLISHED", event=starting_in(minutes=30))
    add_registration(event)

    assert reminders.send_due() == {"24h": 0, "1h": 1}
    assert reminders.send_due() == {"24h": 0, "1h": 0}
    assert [lead for _, lead in reminded()] == ["1h"]


def test_who_is_not_reminded():
    for fields in (
        {"status": "PUBLISHED", "event": starting_in(days=3)},  # not yet
        {"status": "PUBLISHED", "event": starting_in(minutes=-5)},  # already started
        {"status": "DRAFT", "event": starting_in(hours=5)},
        {"status": "CLOSED", "event": starting_in(hours=5)},  # cancelled
    ):
        add_registration(make_event(**fields))

    assert reminders.send_due() == {"24h": 0, "1h": 0}
    assert not Notification.objects.exists()


def test_someone_who_switched_event_messages_off_is_left_alone():
    event = make_event(status="PUBLISHED", event=starting_in(hours=5))
    quiet, keen = add_registration(event).user, add_registration(event).user
    notifications.set_preferences(user=quiet, choices={Category.EVENTS: (False, False)})

    assert reminders.send_due()["24h"] == 1
    assert reminded() == [(keen.email, "24h")]
    assert reminders.send_due()["24h"] == 0


def test_a_run_that_dies_halfway_is_finished_by_the_next_without_repeating(monkeypatch):
    event = make_event(status="PUBLISHED", event=starting_in(hours=5))
    people = [add_registration(event).user for _ in range(3)]
    real, calls = reminders.notify, []

    def flaky(**kwargs):
        calls.append(kwargs["recipient"])
        if len(calls) == 2:
            raise ConnectionError("the database went away")
        return real(**kwargs)

    monkeypatch.setattr(reminders, "notify", flaky)
    with pytest.raises(ConnectionError):
        reminders.send_due()
    assert len(reminded()) == 1
    assert EventDetail.objects.get(pk=event.pk).reminder_24h_sent_at is None

    monkeypatch.setattr(reminders, "notify", real)
    # Three people are still owed a look; only the two who were missed are told.
    assert reminders.send_due()["24h"] == 2
    assert sorted(email for email, _ in reminded()) == sorted(user.email for user in people)


def test_someone_who_registers_after_the_reminder_went_out_still_gets_the_next_one():
    event = make_event(status="PUBLISHED", event=starting_in(hours=5))
    early = add_registration(event).user
    reminders.send_due()
    late = add_registration(event, UserFactory()).user

    EventDetail.objects.filter(pk=event.pk).update(**starting_in(minutes=30))
    reminders.send_due()

    assert sorted(reminded()) == sorted(
        [(early.email, "24h"), (early.email, "1h"), (late.email, "1h")]
    )
