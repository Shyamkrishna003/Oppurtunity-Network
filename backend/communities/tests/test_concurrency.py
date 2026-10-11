"""Races that the locks and constraints must settle. Real threads, real transactions."""

import threading

import pytest
from django.db import connection

from common.errors import Conflict
from communities import services
from communities.models import CommunityMember
from communities.tests.factories import CommunityMemberFactory, community_with_roles
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
        thread.join(timeout=20)
    return outcomes


def errors(outcomes):
    return [outcome for outcome in outcomes if isinstance(outcome, Exception)]


def owners(community) -> int:
    return CommunityMember.objects.filter(
        community=community, role="OWNER", status="ACTIVE"
    ).count()


def test_joining_several_times_at_once_creates_one_membership():
    community, _ = community_with_roles()
    user = UserFactory()

    outcomes = run_together(
        *[lambda: services.join(user=user, community_id=community.pk) for _ in range(5)]
    )

    assert errors(outcomes) == []
    rows = CommunityMember.objects.filter(community=community, user=user)
    assert [row.status for row in rows] == ["ACTIVE"]


def test_two_owners_leaving_at_once_leaves_one_owner():
    community, members = community_with_roles()
    first = members["OWNER"]
    second = CommunityMemberFactory(community=community, role="OWNER")

    outcomes = run_together(
        lambda: services.leave(user=first.user, community_id=community.pk),
        lambda: services.leave(user=second.user, community_id=community.pk),
    )

    (error,) = errors(outcomes)
    assert isinstance(error, Conflict)
    assert error.get_codes() == "last_owner"
    assert owners(community) == 1


def test_two_owners_demoting_each_other_leaves_one_owner():
    community, members = community_with_roles()
    first = members["OWNER"]
    second = CommunityMemberFactory(community=community, role="OWNER")

    outcomes = run_together(
        lambda: services.change_role(
            actor=first.user, community_id=community.pk, member_id=second.pk, role="ADMIN"
        ),
        lambda: services.change_role(
            actor=second.user, community_id=community.pk, member_id=first.pk, role="ADMIN"
        ),
    )

    assert len(errors(outcomes)) == 1
    assert owners(community) == 1


def test_approving_and_rejecting_one_request_at_once_settles_on_one_outcome():
    community, members = community_with_roles("ADMIN", join_policy="APPROVAL")
    pending = CommunityMemberFactory(community=community, status="PENDING")
    target = {"community_id": community.pk, "member_id": pending.pk}

    outcomes = run_together(
        lambda: services.approve(actor=members["OWNER"].user, **target),
        lambda: services.reject(actor=members["ADMIN"].user, **target),
    )

    # Whichever ran second found the request already decided.
    assert len(errors(outcomes)) == 1
    pending.refresh_from_db()
    assert pending.status in ("ACTIVE", "REJECTED")
