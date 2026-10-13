"""Races the event lock must settle. Real threads, real transactions."""

import threading

import pytest
from django.db import connection

from events import registrations
from events.models import EventDetail, EventRegistration
from events.tests.factories import add_registration, make_event
from users.tests.factories import UserFactory

# Committed transactions are needed for threads to see each other's work; the serialized
# rollback restores migration-seeded data for the tests that run afterwards.
pytestmark = pytest.mark.django_db(transaction=True, serialized_rollback=True)


def run_together(*calls):
    """Start every call at the same instant; return each one's result or exception."""
    barrier = threading.Barrier(len(calls))
    outcomes = [None] * len(calls)

    def run(index, call):
        barrier.wait()
        try:
            outcomes[index] = call()
        except Exception as exc:
            outcomes[index] = exc
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=item) for item in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return outcomes


def consistent(event) -> tuple[int, int, int]:
    """(stored count, people going, people waiting), having checked they agree."""
    detail = EventDetail.objects.get(pk=event.pk)
    rows = EventRegistration.objects.filter(event_id=event.pk)
    going = rows.filter(status="CONFIRMED").count()
    assert detail.confirmed_count == going
    assert detail.capacity is None or going <= detail.capacity
    return detail.confirmed_count, going, rows.filter(status="WAITLISTED").count()


def test_many_people_and_one_place():
    event = make_event(status="PUBLISHED", event={"capacity": 1})
    people = [UserFactory() for _ in range(8)]

    outcomes = run_together(
        *(
            (lambda user=user: registrations.register(user=user, opportunity_id=event.pk))
            for user in people
        )
    )

    assert not [o for o in outcomes if isinstance(o, Exception)], outcomes
    assert consistent(event) == (1, 1, 7)
    # Everyone waiting has their own place in the queue.
    queue = EventRegistration.objects.filter(event_id=event.pk, status="WAITLISTED")
    assert len(set(queue.values_list("waitlisted_at", flat=True))) == 7


def test_the_same_person_registering_twice_at_once_gets_one_registration():
    event = make_event(status="PUBLISHED", event={"capacity": 5})
    user = UserFactory()

    outcomes = run_together(
        *(lambda: registrations.register(user=user, opportunity_id=event.pk) for _ in range(4))
    )

    assert not [o for o in outcomes if isinstance(o, Exception)], outcomes
    assert sum(changed for _, changed in outcomes) == 1
    assert consistent(event) == (1, 1, 0)


def test_a_cancellation_and_new_registrations_never_overbook():
    event = make_event(status="PUBLISHED", event={"capacity": 2})
    leaving = [add_registration(event).user for _ in range(2)]
    waiting = add_registration(event, status="WAITLISTED")
    arriving = [UserFactory() for _ in range(4)]

    outcomes = run_together(
        *(
            (
                lambda user=user: registrations.cancel_registration(
                    user=user, opportunity_id=event.pk
                )
            )
            for user in leaving
        ),
        *(
            (lambda user=user: registrations.register(user=user, opportunity_id=event.pk))
            for user in arriving
        ),
    )

    assert not [o for o in outcomes if isinstance(o, Exception)], outcomes
    count, going, queued = consistent(event)
    # Two places, always both taken, and nobody lost: 1 was waiting, 4 arrived, 2 left.
    assert (count, going, queued) == (2, 2, 3)
    # Whoever was already waiting was ahead of everyone who arrived during the scramble.
    waiting.refresh_from_db()
    assert waiting.status == "CONFIRMED"


def test_growing_the_event_while_people_register_fills_exactly_the_new_places():
    event = make_event(status="PUBLISHED", event={"capacity": 1})
    add_registration(event)
    for _ in range(3):
        add_registration(event, status="WAITLISTED")
    arriving = [UserFactory() for _ in range(3)]

    def grow():
        from django.db import transaction

        with transaction.atomic():
            registrations.set_capacity(event.pk, 4)

    outcomes = run_together(
        grow,
        *(
            (lambda user=user: registrations.register(user=user, opportunity_id=event.pk))
            for user in arriving
        ),
    )

    assert not [o for o in outcomes if isinstance(o, Exception)], outcomes
    count, going, queued = consistent(event)
    assert (count, going, queued) == (4, 4, 3)
