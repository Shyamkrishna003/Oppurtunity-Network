"""Permission rules and the membership state machine for communities.

Rules are pure functions of an ``Actor`` (who is acting, and their active role in the
community if any) and the membership being acted on. Rules that need a row count (the
last-owner rule) live in the services, where the count is taken under a lock.
"""

from dataclasses import dataclass
from uuid import UUID

from common.state_machine import StateMachine, Transition
from communities.models import CommunityMember, CommunityRole, MemberStatus

_OWNER, _ADMIN, _MODERATOR, _MEMBER = (
    CommunityRole.OWNER,
    CommunityRole.ADMIN,
    CommunityRole.MODERATOR,
    CommunityRole.MEMBER,
)
# Roles an ADMIN may assign, change between, remove and ban. The rest needs an OWNER.
_ADMIN_SCOPE = frozenset({_MODERATOR, _MEMBER})

S = MemberStatus


@dataclass(frozen=True)
class Actor:
    user_id: UUID
    # The actor's role if they are an active member, otherwise None.
    role: CommunityRole | None = None


def actor_for(user_id: UUID, membership: CommunityMember | None) -> Actor:
    active = membership is not None and membership.status == S.ACTIVE
    return Actor(user_id, CommunityRole(membership.role) if active and membership else None)


def is_member(actor: Actor) -> bool:
    return actor.role is not None


def can_manage(actor: Actor) -> bool:
    """Edit the community and its rules, invite, and see invited and banned people."""
    return actor.role in (_OWNER, _ADMIN)


def can_review_requests(actor: Actor) -> bool:
    """See and approve requests to join."""
    return actor.role in (_OWNER, _ADMIN, _MODERATOR)


def can_read_audit(actor: Actor) -> bool:
    """Read the record of what was done in the community. Owners only: it names people."""
    return actor.role == _OWNER


def assignable_roles(actor: Actor) -> frozenset[CommunityRole]:
    if actor.role == _OWNER:
        return frozenset(CommunityRole)
    if actor.role == _ADMIN:
        return _ADMIN_SCOPE
    return frozenset()


def _is_self(actor: Actor, member: CommunityMember) -> bool:
    return actor.user_id == member.user_id


def _is_manager(actor: Actor, member: CommunityMember) -> bool:
    return can_manage(actor) and not _is_self(actor, member)


def _is_reviewer(actor: Actor, member: CommunityMember) -> bool:
    return can_review_requests(actor) and not _is_self(actor, member)


def _outranks(actor: Actor, member: CommunityMember) -> bool:
    """Admins act on moderators and members; only owners act on admins and owners."""
    return not _is_self(actor, member) and CommunityRole(member.role) in assignable_roles(actor)


def can_change_role(actor: Actor, member: CommunityMember, new_role: CommunityRole) -> bool:
    # Nobody changes their own role, so nobody can promote themselves.
    return (
        member.status == S.ACTIVE
        and _outranks(actor, member)
        and new_role in assignable_roles(actor)
    )


# Which transition a caller gets is decided by the service (for example, joining leads to
# ACTIVE or PENDING depending on the community's join policy); the machine only says
# whether that actor may make that move at all.
_FORMER = (S.LEFT, S.REJECTED, S.REMOVED)

MEMBERSHIP = StateMachine(
    "community membership",
    [
        # Requests to join.
        Transition(S.PENDING, S.ACTIVE, policy=_is_reviewer),
        Transition(S.PENDING, S.REJECTED, policy=_is_manager),
        Transition(S.PENDING, S.LEFT, policy=_is_self),  # withdraw the request
        # Invitations.
        Transition(S.INVITED, S.ACTIVE, policy=_is_self),
        Transition(S.INVITED, S.LEFT, policy=_is_self),  # decline
        Transition(S.INVITED, S.REMOVED, policy=_is_manager),  # withdraw the invitation
        # Active members.
        Transition(S.ACTIVE, S.LEFT, policy=_is_self),
        Transition(S.ACTIVE, S.REMOVED, policy=_outranks),
        Transition(S.ACTIVE, S.BANNED, policy=_outranks),
        # Coming back: by joining again, or by a new invitation.
        *[Transition(former, S.ACTIVE, policy=_is_self) for former in _FORMER],
        *[Transition(former, S.PENDING, policy=_is_self) for former in _FORMER],
        *[Transition(former, S.INVITED, policy=_is_manager) for former in _FORMER],
        # A ban ends only when a manager lifts it; the person may then join again.
        Transition(S.BANNED, S.REMOVED, policy=_is_manager),
    ],
)
