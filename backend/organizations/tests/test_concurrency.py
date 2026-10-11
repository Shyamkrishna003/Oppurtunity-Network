"""Races that the row lock and constraints must settle. Real threads, real transactions."""

import threading

import pytest
from django.db import connection

from common.errors import Conflict
from organizations import services, tokens
from organizations.models import OrganizationInvitation, OrganizationMember
from organizations.tests.factories import MemberFactory, organization_with_roles
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


def owners(organization) -> int:
    return OrganizationMember.objects.filter(
        organization=organization, role="OWNER", status="ACTIVE"
    ).count()


def test_two_owners_demoting_each_other_leaves_one_owner():
    organization, members = organization_with_roles()
    first, second = members["OWNER"], MemberFactory(organization=organization, role="OWNER")

    outcomes = run_together(
        lambda: services.change_role(
            actor=first.user, organization_id=organization.pk, member_id=second.pk, role="ADMIN"
        ),
        lambda: services.change_role(
            actor=second.user, organization_id=organization.pk, member_id=first.pk, role="ADMIN"
        ),
    )

    assert len(errors(outcomes)) == 1
    assert owners(organization) == 1


def test_two_owners_leaving_at_once_leaves_one_owner():
    organization, members = organization_with_roles()
    first, second = members["OWNER"], MemberFactory(organization=organization, role="OWNER")

    outcomes = run_together(
        lambda: services.leave(user=first.user, organization_id=organization.pk),
        lambda: services.leave(user=second.user, organization_id=organization.pk),
    )

    (error,) = errors(outcomes)
    assert isinstance(error, Conflict)
    assert error.get_codes() == "last_owner"
    assert owners(organization) == 1


def test_an_invitation_accepted_twice_at_once_creates_one_membership():
    organization, members = organization_with_roles()
    invitee = UserFactory()
    invitation = services.invite(
        actor=members["OWNER"].user,
        organization_id=organization.pk,
        email=invitee.email,
        role="MEMBER",
    )
    token = tokens.invitation_token(invitation.pk)

    outcomes = run_together(
        *[lambda: services.accept_invitation(user=invitee, token=token) for _ in range(4)]
    )

    assert len(errors(outcomes)) == 3
    assert all(isinstance(error, Conflict) for error in errors(outcomes))
    assert OrganizationMember.objects.filter(organization=organization, user=invitee).count() == 1


def test_duplicate_invitations_sent_at_once_create_one():
    organization, members = organization_with_roles()
    owner = members["OWNER"].user

    outcomes = run_together(
        *[
            lambda: services.invite(
                actor=owner,
                organization_id=organization.pk,
                email="new@example.com",
                role="MEMBER",
            )
            for _ in range(4)
        ]
    )

    assert len(errors(outcomes)) == 3
    assert OrganizationInvitation.objects.filter(status="PENDING").count() == 1
