"""Every write to organizations, memberships and invitations.

Membership mutations lock the organization row first. That serialises them per organization,
so permission checks and the owner count are always made against settled state: two owners
demoting each other at the same moment cannot leave the organization without an owner.
"""

import secrets
from functools import partial
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import PermissionDenied

from audit.services import record
from common.errors import BusinessRuleViolation, Conflict
from common.tasks import enqueue
from organizations import policies, tasks, tokens
from organizations.models import (
    InvitationStatus,
    MembershipStatus,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    OrganizationRole,
    OrganizationStatus,
)
from users.models import User, UserManager

_SLUG_ATTEMPTS = 5


def _lock(organization_id: UUID) -> Organization:
    organization = Organization.objects.select_for_update().filter(pk=organization_id).first()
    if organization is None:
        raise Http404
    return organization


def _require_active(organization: Organization) -> None:
    if organization.status != OrganizationStatus.ACTIVE:
        raise BusinessRuleViolation(
            "This organization is suspended.", code="organization_suspended"
        )


def _membership(organization: Organization, user: User) -> OrganizationMember | None:
    return OrganizationMember.objects.filter(
        organization=organization, user=user, status=MembershipStatus.ACTIVE
    ).first()


def _member(organization: Organization, member_id: UUID) -> OrganizationMember:
    member = OrganizationMember.objects.filter(
        organization=organization, pk=member_id, status=MembershipStatus.ACTIVE
    ).first()
    if member is None:
        raise Http404
    return member


def _owner_count(organization: Organization) -> int:
    return OrganizationMember.objects.filter(
        organization=organization, status=MembershipStatus.ACTIVE, role=OrganizationRole.OWNER
    ).count()


def _last_owner() -> Conflict:
    return Conflict(
        "An organization must keep at least one owner. Make someone else an owner first.",
        code="last_owner",
    )


# --- Organization -----------------------------------------------------------------------


def create_organization(*, creator: User, name: str, **details: Any) -> Organization:
    """Create an organization with ``creator`` as its first owner."""
    if not creator.is_email_verified:
        raise PermissionDenied("Verify your email address to do this.", code="email_not_verified")

    base = slugify(name)[:120] or "organization"
    for attempt in range(_SLUG_ATTEMPTS):
        # The readable slug first; if it is taken, the same slug with a short random suffix.
        slug = base if attempt == 0 else f"{base}-{secrets.token_hex(3)}"
        if Organization.objects.filter(slug=slug).exists():
            continue
        try:
            with transaction.atomic():
                organization = Organization.objects.create(name=name, slug=slug, **details)
                OrganizationMember.objects.create(
                    organization=organization,
                    user=creator,
                    role=OrganizationRole.OWNER,
                    joined_at=timezone.now(),
                )
                record(
                    action="organization.created",
                    target=organization,
                    actor=creator,
                    organization_id=organization.pk,
                )
                return organization
        except IntegrityError:
            continue  # lost a race for the slug; try another
    raise Conflict("Could not create the organization. Try again.", code="slug_unavailable")


def update_organization(
    *, actor: User, organization_id: UUID, changes: dict[str, Any]
) -> Organization:
    with transaction.atomic():
        organization = _lock(organization_id)
        _require_active(organization)
        if not policies.can_manage(_membership(organization, actor)):
            raise PermissionDenied()
        for field, value in changes.items():
            setattr(organization, field, value)
        organization.save(update_fields=[*changes, "updated_at"])
        record(
            action="organization.updated",
            target=organization,
            actor=actor,
            organization_id=organization.pk,
            metadata={"fields": sorted(changes)},
        )
        return organization


# --- Invitations ------------------------------------------------------------------------


def invite(
    *, actor: User, organization_id: UUID, email: str, role: OrganizationRole
) -> OrganizationInvitation:
    """Invite an email address. The link is emailed; nobody becomes a member until it is
    accepted by a signed-in user whose verified email is that address."""
    email = UserManager.normalize_email(email)
    now = timezone.now()
    with transaction.atomic():
        organization = _lock(organization_id)
        _require_active(organization)
        if not policies.can_invite(_membership(organization, actor), role):
            raise PermissionDenied()
        if OrganizationMember.objects.filter(
            organization=organization, user__email=email, status=MembershipStatus.ACTIVE
        ).exists():
            raise Conflict("This person is already a member.", code="already_member")

        pending = OrganizationInvitation.objects.filter(
            organization=organization, email=email, status=InvitationStatus.PENDING
        )
        # An invitation that ran out of time no longer blocks a new one.
        pending.filter(expires_at__lte=now).update(status=InvitationStatus.EXPIRED)
        if pending.exists():
            raise Conflict(
                "This address already has an open invitation.", code="invitation_pending"
            )

        invitation = OrganizationInvitation(
            organization=organization,
            email=email,
            role=role,
            invited_by=actor,
            expires_at=now + settings.ORGANIZATION_INVITATION_LIFETIME,
        )
        invitation.token_hash = tokens.hash_token(tokens.invitation_token(invitation.pk))
        invitation.save()
        record(
            action="organization.member_invited",
            target=invitation,
            actor=actor,
            organization_id=organization.pk,
            metadata={"role": role},
        )
        transaction.on_commit(partial(enqueue, tasks.send_invitation_email, str(invitation.pk)))
        return invitation


def revoke_invitation(*, actor: User, organization_id: UUID, invitation_id: UUID) -> None:
    with transaction.atomic():
        organization = _lock(organization_id)
        invitation = OrganizationInvitation.objects.filter(
            organization=organization, pk=invitation_id
        ).first()
        if invitation is None:
            raise Http404
        # Whoever could have sent this invitation may withdraw it.
        role = OrganizationRole(invitation.role)
        if not policies.can_invite(_membership(organization, actor), role):
            raise PermissionDenied()
        _close_invitation(invitation, InvitationStatus.REVOKED)
        record(
            action="organization.invitation_revoked",
            target=invitation,
            actor=actor,
            organization_id=organization.pk,
        )


def get_invitation(*, user: User, token: str) -> OrganizationInvitation:
    """The invitation behind a link, if it was sent to ``user``'s address."""
    invitation = (
        OrganizationInvitation.objects.select_related("organization", "invited_by__profile")
        .filter(token_hash=tokens.hash_token(token))
        .first()
    )
    if invitation is None:
        raise Http404
    if invitation.email != user.email:
        raise PermissionDenied(
            "This invitation was sent to a different email address. "
            "Sign in with the account that uses that address.",
            code="invitation_email_mismatch",
        )
    return invitation


def _close_invitation(invitation: OrganizationInvitation, status: InvitationStatus) -> None:
    """Move a pending, unexpired invitation to ``status``; an invitation is answered once.

    A conditional update: of several concurrent attempts exactly one finds it still pending.
    """
    now = timezone.now()
    updated = OrganizationInvitation.objects.filter(
        pk=invitation.pk, status=InvitationStatus.PENDING, expires_at__gt=now
    ).update(status=status, responded_at=now, updated_at=now)
    if updated:
        return
    invitation.refresh_from_db()
    if invitation.status == InvitationStatus.PENDING:
        raise Conflict("This invitation has expired.", code="invitation_expired")
    raise Conflict("This invitation is no longer open.", code="invitation_closed")


def accept_invitation(*, user: User, token: str) -> OrganizationMember:
    if not user.is_email_verified:
        raise PermissionDenied("Verify your email address to do this.", code="email_not_verified")
    invitation = get_invitation(user=user, token=token)
    now = timezone.now()
    with transaction.atomic():
        organization = _lock(invitation.organization_id)
        _require_active(organization)
        _close_invitation(invitation, InvitationStatus.ACCEPTED)
        # A former member's row is reused, so there is one membership history per person.
        membership, created = OrganizationMember.objects.get_or_create(
            organization=organization,
            user=user,
            defaults={"role": invitation.role, "joined_at": now},
        )
        if not created and membership.status != MembershipStatus.ACTIVE:
            membership.status = MembershipStatus.ACTIVE
            membership.role = invitation.role
            membership.joined_at = now
            membership.save(update_fields=["status", "role", "joined_at", "updated_at"])
        record(
            action="organization.member_joined",
            target=membership,
            actor=user,
            organization_id=organization.pk,
            metadata={"role": membership.role, "invitation_id": str(invitation.pk)},
        )
        return membership


def decline_invitation(*, user: User, token: str) -> None:
    invitation = get_invitation(user=user, token=token)
    with transaction.atomic():
        _close_invitation(invitation, InvitationStatus.DECLINED)
        record(
            action="organization.invitation_declined",
            target=invitation,
            actor=user,
            organization_id=invitation.organization_id,
        )


# --- Members ----------------------------------------------------------------------------


def change_role(
    *, actor: User, organization_id: UUID, member_id: UUID, role: OrganizationRole
) -> OrganizationMember:
    with transaction.atomic():
        organization = _lock(organization_id)
        _require_active(organization)
        target = _member(organization, member_id)
        if not policies.can_change_role(_membership(organization, actor), target, role):
            raise PermissionDenied()
        previous = target.role
        if previous == role:
            return target
        if previous == OrganizationRole.OWNER and _owner_count(organization) <= 1:
            raise _last_owner()
        target.role = role
        target.save(update_fields=["role", "updated_at"])
        record(
            action="organization.role_changed",
            target=target,
            actor=actor,
            organization_id=organization.pk,
            metadata={"from": previous, "to": role},
        )
        return target


def remove_member(*, actor: User, organization_id: UUID, member_id: UUID) -> None:
    with transaction.atomic():
        organization = _lock(organization_id)
        target = _member(organization, member_id)
        if not policies.can_remove(_membership(organization, actor), target):
            raise PermissionDenied()
        if target.role == OrganizationRole.OWNER and _owner_count(organization) <= 1:
            raise _last_owner()
        target.status = MembershipStatus.REMOVED
        target.save(update_fields=["status", "updated_at"])
        record(
            action="organization.member_removed",
            target=target,
            actor=actor,
            organization_id=organization.pk,
            metadata={"role": target.role},
        )


def leave(*, user: User, organization_id: UUID) -> None:
    with transaction.atomic():
        organization = _lock(organization_id)
        membership = _membership(organization, user)
        if membership is None:
            raise Http404
        if membership.role == OrganizationRole.OWNER and _owner_count(organization) <= 1:
            raise _last_owner()
        membership.status = MembershipStatus.LEFT
        membership.save(update_fields=["status", "updated_at"])
        record(
            action="organization.member_left",
            target=membership,
            actor=user,
            organization_id=organization.pk,
            metadata={"role": membership.role},
        )


def transfer_ownership(*, actor: User, organization_id: UUID, member_id: UUID) -> None:
    """Make another member an owner and step down to admin, as one change."""
    with transaction.atomic():
        organization = _lock(organization_id)
        _require_active(organization)
        current = _membership(organization, actor)
        target = _member(organization, member_id)
        if current is None or not policies.can_transfer_ownership(current):
            raise PermissionDenied()
        if target.pk == current.pk:
            raise BusinessRuleViolation("You already own this organization.", code="already_owner")
        previous = target.role
        target.role = OrganizationRole.OWNER
        target.save(update_fields=["role", "updated_at"])
        current.role = OrganizationRole.ADMIN
        current.save(update_fields=["role", "updated_at"])
        record(
            action="organization.ownership_transferred",
            target=target,
            actor=actor,
            organization_id=organization.pk,
            metadata={"from": previous, "previous_owner_membership": str(current.pk)},
        )


def set_membership_visibility(
    *, user: User, organization_id: UUID, member_id: UUID, is_public: bool
) -> OrganizationMember:
    """Members choose for themselves whether outsiders see that they belong; nobody,
    whatever their role, can choose it for someone else."""
    with transaction.atomic():
        organization = _lock(organization_id)
        membership = _member(organization, member_id)
        if membership.user_id != user.pk:
            raise PermissionDenied()
        membership.is_public = is_public
        membership.save(update_fields=["is_public", "updated_at"])
        return membership
