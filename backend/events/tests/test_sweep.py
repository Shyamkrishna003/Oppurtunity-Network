"""The periodic sweep that moves events along as their times pass."""

import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from audit.models import AuditLog
from events import services, tasks
from events.models import EventStatus
from events.policies import EVENT, UPCOMING
from events.tests.factories import make_event
from opportunities import services as opportunities
from opportunities.models import CloseReason, Opportunity

pytestmark = pytest.mark.django_db


def ago(**delta):
    return timezone.now() - timedelta(**delta)


def ahead(**delta):
    return timezone.now() + timedelta(**delta)


def state(event) -> tuple[str, str]:
    event.refresh_from_db()
    event.event.refresh_from_db()
    return event.status, event.event.event_status


def test_registration_opens_at_its_time():
    due = make_event(
        status="PUBLISHED",
        event={"event_status": "SCHEDULED", "registration_opens_at": ago(minutes=1)},
    )
    later = make_event(
        status="PUBLISHED",
        event={"event_status": "SCHEDULED", "registration_opens_at": ahead(days=1)},
    )

    assert services.advance_states() == {"opened": 1, "closed": 0, "completed": 0}

    assert state(due) == ("PUBLISHED", "REGISTRATION_OPEN")
    assert state(later) == ("PUBLISHED", "SCHEDULED")
    log = AuditLog.objects.get(action="event.registration_opened")
    assert (log.actor, log.target_id) == (None, due.pk)


def test_registration_closes_at_the_deadline_or_when_the_event_starts():
    past_deadline = make_event(status="PUBLISHED", deadline=ago(minutes=1))
    started = make_event(
        status="PUBLISHED", event={"start_at": ago(minutes=5), "end_at": ahead(hours=1)}
    )
    still_open = make_event(status="PUBLISHED", deadline=ahead(days=1))

    assert services.advance_states() == {"opened": 0, "closed": 2, "completed": 0}

    assert state(past_deadline) == ("PUBLISHED", "REGISTRATION_CLOSED")
    assert state(started) == ("PUBLISHED", "REGISTRATION_CLOSED")
    assert state(still_open) == ("PUBLISHED", "REGISTRATION_OPEN")


@pytest.mark.parametrize("status", sorted(UPCOMING))
def test_an_event_that_has_ended_is_completed_and_its_opportunity_closed(status):
    event = make_event(
        status="PUBLISHED",
        event={"event_status": status, "start_at": ago(hours=3), "end_at": ago(minutes=1)},
    )

    moved = services.advance_states()

    assert moved["completed"] == 1
    assert state(event) == ("CLOSED", "COMPLETED")
    assert event.close_reason == CloseReason.COMPLETED
    assert event.closed_at is not None
    assert AuditLog.objects.filter(action="event.completed", target_id=event.pk).count() == 1


def test_the_sweep_leaves_alone_what_is_not_its_business():
    over = {"start_at": ago(hours=3), "end_at": ago(hours=1)}
    draft = make_event(event=over)
    cancelled = make_event(status="CLOSED", event=over)
    archived = make_event(status="ARCHIVED", event=over)
    upcoming = make_event(status="PUBLISHED")
    before = [state(event) for event in (draft, cancelled, archived, upcoming)]

    assert services.advance_states() == {"opened": 0, "closed": 0, "completed": 0}

    assert [state(event) for event in (draft, cancelled, archived, upcoming)] == before
    assert not AuditLog.objects.filter(action__startswith="event.").exists()


def test_running_the_sweep_again_changes_and_records_nothing_more():
    make_event(status="PUBLISHED", deadline=ago(minutes=1))
    make_event(status="PUBLISHED", event={"start_at": ago(hours=3), "end_at": ago(minutes=1)})

    first = tasks.advance_states()
    logged = AuditLog.objects.count()
    second = tasks.advance_states()

    assert first == {"opened": 0, "closed": 2, "completed": 1}
    assert second == {"opened": 0, "closed": 0, "completed": 0}
    assert AuditLog.objects.count() == logged


def test_a_completed_event_cannot_be_cancelled_afterwards(api_as):
    event = make_event(status="PUBLISHED", event={"start_at": ago(hours=3), "end_at": ago(hours=1)})
    services.advance_states()

    response = api_as(event.creator).post(
        f"/api/v1/opportunities/{event.pk}/close/", {"reason": "CANCELLED"}
    )

    # Closing something closed changes nothing: it stays completed.
    assert response.status_code == 200
    assert response.json()["event"]["event_status"] == "COMPLETED"
    assert response.json()["close_reason"] == "COMPLETED"


def test_the_shape_of_the_event_state_machine():
    assert {s for s in EventStatus.values if EVENT.is_terminal(s)} == {"COMPLETED", "CANCELLED"}
    assert EVENT.targets("SCHEDULED") == {"REGISTRATION_OPEN", "COMPLETED", "CANCELLED"}
    assert EVENT.targets("REGISTRATION_CLOSED") == {
        "REGISTRATION_OPEN",
        "COMPLETED",
        "CANCELLED",
    }


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_cancelling_at_the_moment_an_event_ends_leaves_one_outcome():
    event = make_event(
        status="PUBLISHED", event={"start_at": ago(hours=3), "end_at": ago(seconds=1)}
    )
    barrier = threading.Barrier(2)
    outcomes = []

    def run(call):
        barrier.wait()
        try:
            outcomes.append(call())
        except Exception as exc:
            outcomes.append(exc)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=run, args=(services.advance_states,)),
        threading.Thread(
            target=run,
            args=(
                lambda: opportunities.close(
                    actor=event.creator, opportunity_id=event.pk, reason=CloseReason.CANCELLED
                ),
            ),
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    status, event_status = state(event)
    assert status == "CLOSED"
    # Whichever got there first decided; the two rows never disagree.
    assert (event_status, event.close_reason) in {
        ("COMPLETED", "COMPLETED"),
        ("CANCELLED", "CANCELLED"),
    }
    assert Opportunity.objects.get(pk=event.pk).closed_at is not None
    decided = AuditLog.objects.filter(
        action__in=["event.completed", "opportunity.closed"], target_id=event.pk
    )
    assert decided.count() == 1
