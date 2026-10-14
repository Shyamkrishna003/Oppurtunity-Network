"""Permission rules for organizations: pure functions of the actor's and target's memberships.

``None`` stands for "no active membership". Rules that depend on counting rows (the
last-owner rule) live in the services, where the count is taken under a lock.
"""

from organizations.models import MembershipStatus, OrganizationMember, OrganizationRole

_MANAGERS = frozenset({OrganizationRole.OWNER, OrganizationRole.ADMIN})
# Roles an ADMIN may hand out, change between, and remove. Everything else needs an OWNER.
_ADMIN_SCOPE = frozenset({OrganizationRole.RECRUITER, OrganizationRole.MEMBER})


def _is_active(membership: OrganizationMember | None) -> bool:
    return membership is not None and membership.status == MembershipStatus.ACTIVE


def _role(membership: OrganizationMember | None) -> OrganizationRole | None:
    if membership is None or membership.status != MembershipStatus.ACTIVE:
        return None
    return OrganizationRole(membership.role)


def is_member(membership: OrganizationMember | None) -> bool:
    return _is_active(membership)


def can_manage(membership: OrganizationMember | None) -> bool:
    """Edit the organization's details and see its invitations."""
    return _role(membership) in _MANAGERS


def can_read_audit(membership: OrganizationMember | None) -> bool:
    """Read the record of what was done in the organization. Owners only: it names people."""
    return _role(membership) == OrganizationRole.OWNER


def assignable_roles(membership: OrganizationMember | None) -> frozenset[OrganizationRole]:
    """Roles the actor may invite someone as, or give to an existing member."""
    role = _role(membership)
    if role == OrganizationRole.OWNER:
        return frozenset(OrganizationRole)
    if role == OrganizationRole.ADMIN:
        return _ADMIN_SCOPE
    return frozenset()


def can_invite(membership: OrganizationMember | None, role: OrganizationRole) -> bool:
    return role in assignable_roles(membership)


def can_change_role(
    actor: OrganizationMember | None, target: OrganizationMember, new_role: OrganizationRole
) -> bool:
    if actor is None or actor.pk == target.pk or not _is_active(target):
        return False  # nobody changes their own role, so nobody can promote themselves
    allowed = assignable_roles(actor)
    return new_role in allowed and OrganizationRole(target.role) in allowed


def can_remove(actor: OrganizationMember | None, target: OrganizationMember) -> bool:
    """Remove someone else. Leaving on one's own is a separate action."""
    if actor is None or actor.pk == target.pk or not _is_active(target):
        return False
    return OrganizationRole(target.role) in assignable_roles(actor)


def can_transfer_ownership(membership: OrganizationMember | None) -> bool:
    return _role(membership) == OrganizationRole.OWNER
