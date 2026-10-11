"""Permission rules and the lifecycle state machine for opportunities."""

from dataclasses import dataclass

from common.state_machine import StateMachine, Transition
from opportunities.models import Opportunity, OpportunityStatus
from organizations.models import MembershipStatus, OrganizationMember, OrganizationRole
from users.models import User

# Roles that publish and manage an organization's opportunities.
POSTING_ROLES = frozenset(
    {OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.RECRUITER}
)

S = OpportunityStatus


def can_post_for(membership: OrganizationMember | None) -> bool:
    """Whether a membership lets its holder create and manage the organization's opportunities."""
    return (
        membership is not None
        and membership.status == MembershipStatus.ACTIVE
        and OrganizationRole(membership.role) in POSTING_ROLES
    )


def can_manage(user: User, opportunity: Opportunity, membership: OrganizationMember | None) -> bool:
    """An organization's opportunity is managed by its owners, admins and recruiters, whoever
    created it: someone who leaves the organization leaves its opportunities behind. A
    personal opportunity is managed by its creator.

    ``membership`` is the user's membership of ``opportunity.organization``, if any.
    """
    if opportunity.organization_id is None:
        return opportunity.creator_id == user.pk
    return (
        membership is not None
        and membership.organization_id == opportunity.organization_id
        and can_post_for(membership)
    )


@dataclass(frozen=True)
class Manager:
    """The actor for a lifecycle change made by a person. System changes pass ``None``."""

    user: User


def _by_manager(actor: Manager | None, opportunity: Opportunity) -> bool:
    return actor is not None


def _by_system(actor: Manager | None, opportunity: Opportunity) -> bool:
    return actor is None


# The service establishes that a person manages the opportunity before building a Manager,
# so here the question is only whether the move is open to people, to the system, or both.
LIFECYCLE = StateMachine(
    "opportunity",
    [
        Transition(S.DRAFT, S.PUBLISHED, policy=_by_manager),
        Transition(S.PUBLISHED, S.CLOSED, policy=_by_manager),
        # Only the deadline expires an opportunity; a person closes it instead.
        Transition(S.PUBLISHED, S.EXPIRED, policy=_by_system),
        Transition(S.CLOSED, S.ARCHIVED),
        Transition(S.EXPIRED, S.ARCHIVED),
    ],
)

# What may still be changed once people can see the opportunity: enough to fix a typo or
# extend the deadline, not enough to turn it into a different opportunity under applicants.
EDITABLE_WHEN_PUBLISHED = frozenset({"description", "deadline"})


def editable_fields(opportunity: Opportunity) -> frozenset[str] | None:
    """Base fields that may change in the current state. ``None`` means all of them."""
    if opportunity.status == S.DRAFT:
        return None
    if opportunity.status == S.PUBLISHED:
        return EDITABLE_WHEN_PUBLISHED
    return frozenset()
