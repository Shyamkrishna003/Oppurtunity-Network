"""Races that the locks and constraints must settle. Real threads, real transactions."""

import pytest
from django.db import IntegrityError, transaction

from common.errors import Conflict
from communities.tests.test_concurrency import errors, run_together
from connections import services
from connections.models import Connection
from connections.tests.factories import make_connection
from notifications.models import Notification
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db(transaction=True, serialized_rollback=True)


def test_asking_several_times_at_once_creates_one_request():
    alice, bob = UserFactory(), UserFactory()

    outcomes = run_together(*[lambda: services.request(user=alice, user_id=bob.pk)] * 4)

    assert errors(outcomes) == []
    assert sorted(created for _, created in outcomes) == [False, False, False, True]
    assert Connection.objects.count() == 1
    assert Notification.objects.count() == 1


def test_two_people_asking_each_other_at_once_end_up_with_one_request():
    alice, bob = UserFactory(), UserFactory()

    outcomes = run_together(
        lambda: services.request(user=alice, user_id=bob.pk),
        lambda: services.request(user=bob, user_id=alice.pk),
    )

    # One request was stored; the other person was told to answer it.
    lost = errors(outcomes)
    assert len(lost) == 1 and isinstance(lost[0], Conflict)
    assert lost[0].get_codes() == "request_waiting"
    connection = Connection.objects.get()
    assert connection.status == "REQUESTED"
    assert Notification.objects.count() == 1


def test_accepting_while_the_request_is_taken_back_has_one_winner():
    alice, bob = UserFactory(), UserFactory()
    connection = make_connection(alice, bob, "REQUESTED")

    outcomes = run_together(
        lambda: services.respond(user=bob, connection_id=connection.pk, accept=True),
        lambda: services.remove(user=alice, connection_id=connection.pk),
    )

    # Either Bob accepted and Alice then ended the connection, or Alice took the request
    # back and Bob found nothing to accept. Both leave no row behind, and never a
    # half-applied one.
    assert not Connection.objects.exists()
    assert len(errors(outcomes)) <= 1


def test_the_database_itself_refuses_a_malformed_pair():
    alice, bob, carol = sorted((UserFactory() for _ in range(3)), key=lambda user: user.pk)
    make_connection(alice, bob)

    with pytest.raises(IntegrityError), transaction.atomic():  # the same pair twice
        Connection.objects.create(user_low=alice, user_high=bob, requested_by=bob)
    with pytest.raises(IntegrityError), transaction.atomic():  # stored the wrong way round
        Connection.objects.create(user_low=carol, user_high=bob, requested_by=bob)
    with pytest.raises(IntegrityError), transaction.atomic():  # with oneself
        Connection.objects.create(user_low=carol, user_high=carol, requested_by=carol)
    with pytest.raises(IntegrityError), transaction.atomic():  # asked by a third person
        Connection.objects.create(user_low=bob, user_high=carol, requested_by=alice)
    with pytest.raises(IntegrityError), transaction.atomic():
        Connection.objects.filter(user_low=alice).update(status="BLOCKED")
