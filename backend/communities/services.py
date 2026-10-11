"""Every write to communities, memberships and rules.

Changes made by one person to another (approve, remove, ban, change role, invite) and
leaving lock the community row first, so permission checks and the owner count are made
against settled state. Joining does not: it only ever touches the caller's own row, and a
popular community must not queue every new member behind one lock.
"""

import secrets
from functools import partial
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import PermissionDenied

from audit.services import record
from common.errors import BusinessRuleViolation, Conflict, InvalidTransition
from common.tasks import enqueue
from communities import policies, selectors, tasks
from communities.models import (
    Community,
    CommunityMember,
    CommunityRole,
    CommunityRule,
    CommunityStatus,
    JoinPolicy,
    MemberStatus,
)
from communities.policies import MEMBERSHIP, Actor
from users.models import User
from users.selectors import get_visible_user

MAX_RULES = 20
_SLUG_ATTEMPTS = 5
S = MemberStatus


def _lock(community_id: UUID) -> Community:
    community = Community.objects.select_for_update().filter(pk=community_id).first()
    if community is None:
        raise Http404
    return community


def _require_active(community: Community) -> None:
    if community.status != CommunityStatus.ACTIVE:
        raise BusinessRuleViolation("This community is suspended.", code="community_suspended")


def _require_verified(user: User) -> None:
    if not user.is_email_verified:
        raise PermissionDenied("Verify your email address to do this.", code="email_not_verified")


def _row(community: Community, user_id: UUID) -> CommunityMember | None:
    return (
        CommunityMember.objects.select_for_update()
        .filter(community=community, user_id=user_id)
        .first()
    )


def _actor(community: Community, user: User) -> Actor:
    return policies.actor_for(user.pk, _row(community, user.pk))


def _member(community: Community, member_id: UUID) -> CommunityMember:
    member = (
        CommunityMember.objects.select_for_update()
        .filter(community=community, pk=member_id)
        .first()
    )
    if member is None:
        raise Http404
    return member


def _owner_count(community: Community) -> int:
    return CommunityMember.objects.filter(
        community=community, status=S.ACTIVE, role=CommunityRole.OWNER
    ).count()


def _is_active_owner(member: CommunityMember) -> bool:
    return member.status == S.ACTIVE and member.role == CommunityRole.OWNER


def _guard_last_owner(community: Community) -> None:
    """Call, with the community locked, before an active owner stops being one."""
    if _owner_count(community) <= 1:
        raise Conflict(
            "A community must keep at least one owner. Make someone else an owner first.",
            code="last_owner",
        )


def _record_change(
    member: CommunityMember, *, by: User, previous: str | None, community: Community
) -> None:
    record(
        action="community.membership_changed",
        target=member,
        actor=by,
        community_id=community.pk,
        metadata={"from": previous, "to": member.status},
    )


def _move(
    member: CommunityMember, target: MemberStatus, *, actor: Actor, by: User, community: Community
) -> bool:
    """Apply a membership transition and everything that always goes with it."""
    previous = member.status
    was_owner = _is_active_owner(member)
    # Permission first: someone who may not make this move learns nothing else about it.
    if not MEMBERSHIP.apply(member, target, actor=actor):
        return False  # already there: a repeated request
    if was_owner:
        _guard_last_owner(community)
    if target == S.ACTIVE:
        member.joined_at = timezone.now()
    else:
        # Roles belong to active members; nobody returns as an admin by rejoining.
        member.role = CommunityRole.MEMBER
    member.save(update_fields=["status", "role", "joined_at", "invited_by", "updated_at"])
    _record_change(member, by=by, previous=previous, community=community)
    return True


# --- Community --------------------------------------------------------------------------


def create_community(*, creator: User, name: str, **details: Any) -> Community:
    """Create a community with ``creator`` as its first owner."""
    _require_verified(creator)
    base = slugify(name)[:120] or "community"
    for attempt in range(_SLUG_ATTEMPTS):
        slug = base if attempt == 0 else f"{base}-{secrets.token_hex(3)}"
        if Community.objects.filter(slug=slug).exists():
            continue
        try:
            with transaction.atomic():
                community = Community.objects.create(name=name, slug=slug, **details)
                CommunityMember.objects.create(
                    community=community,
                    user=creator,
                    role=CommunityRole.OWNER,
                    status=S.ACTIVE,
                    joined_at=timezone.now(),
                )
                record(
                    action="community.created",
                    target=community,
                    actor=creator,
                    community_id=community.pk,
                )
                return community
        except IntegrityError:
            continue  # lost a race for the slug; try another
    raise Conflict("Could not create the community. Try again.", code="slug_unavailable")


def update_community(*, actor: User, community_id: UUID, changes: dict[str, Any]) -> Community:
    with transaction.atomic():
        community = _lock(community_id)
        _require_active(community)
        if not policies.can_manage(_actor(community, actor)):
            raise PermissionDenied()
        for field, value in changes.items():
            setattr(community, field, value)
        community.save(update_fields=[*changes, "updated_at"])
        record(
            action="community.updated",
            target=community,
            actor=actor,
            community_id=community.pk,
            metadata={"fields": sorted(changes)},
        )
        return community


def replace_rules(*, actor: User, community_id: UUID, rules: list[dict[str, str]]) -> None:
    """Make the community's rules exactly ``rules``, in that order."""
    with transaction.atomic():
        community = _lock(community_id)
        _require_active(community)
        if not policies.can_manage(_actor(community, actor)):
            raise PermissionDenied()
        CommunityRule.objects.filter(community=community).delete()
        CommunityRule.objects.bulk_create(
            CommunityRule(community=community, position=position, **rule)
            for position, rule in enumerate(rules, start=1)
        )
        record(
            action="community.rules_updated",
            target=community,
            actor=actor,
            community_id=community.pk,
            metadata={"count": len(rules)},
        )


# --- Joining and leaving ----------------------------------------------------------------


def _join_target(community: Community) -> MemberStatus:
    if community.join_policy == JoinPolicy.OPEN:
        return S.ACTIVE
    if community.join_policy == JoinPolicy.APPROVAL:
        return S.PENDING
    raise BusinessRuleViolation(
        "This community can only be joined by invitation.", code="invitation_required"
    )


def join(*, user: User, community_id: UUID) -> CommunityMember:
    """Join, ask to join, or accept an invitation, whichever applies. Safe to repeat."""
    _require_verified(user)
    community = selectors.get_community(user, community_id)
    _require_active(community)
    with transaction.atomic():
        member = _row(community, user.pk)
        if member is None:
            target = _join_target(community)
            try:
                with transaction.atomic():
                    member = CommunityMember.objects.create(
                        community=community,
                        user=user,
                        status=target,
                        joined_at=timezone.now() if target == S.ACTIVE else None,
                    )
            except IntegrityError:
                # The same person's concurrent request created the row first.
                member = _row(community, user.pk)
                assert member is not None
            else:
                _record_change(member, by=user, previous=None, community=community)
                return member

        if member.status == S.BANNED:
            raise Conflict("You cannot join this community.", code="banned")
        if member.status in (S.ACTIVE, S.PENDING):
            return member
        target = S.ACTIVE if member.status == S.INVITED else _join_target(community)
        actor = policies.actor_for(user.pk, member)
        _move(member, target, actor=actor, by=user, community=community)
        return member


def leave(*, user: User, community_id: UUID) -> None:
    """Leave, decline an invitation, or withdraw a request to join."""
    with transaction.atomic():
        community = _lock(community_id)
        member = _row(community, user.pk)
        if member is None or member.status not in (S.ACTIVE, S.INVITED, S.PENDING):
            raise Http404
        actor = policies.actor_for(user.pk, member)
        _move(member, S.LEFT, actor=actor, by=user, community=community)


# --- Acting on other people -------------------------------------------------------------


def _moderate(
    *,
    actor: User,
    community_id: UUID,
    member_id: UUID,
    target: MemberStatus,
    sources: tuple[MemberStatus, ...],
) -> CommunityMember:
    with transaction.atomic():
        community = _lock(community_id)
        _require_active(community)
        acting = _actor(community, actor)
        member = _member(community, member_id)
        if member.status != target and member.status not in sources:
            raise InvalidTransition("This action does not apply to this person's current state.")
        _move(member, target, actor=acting, by=actor, community=community)
        return member


def approve(*, actor: User, community_id: UUID, member_id: UUID) -> CommunityMember:
    return _moderate(
        actor=actor,
        community_id=community_id,
        member_id=member_id,
        target=S.ACTIVE,
        sources=(S.PENDING,),
    )


def reject(*, actor: User, community_id: UUID, member_id: UUID) -> CommunityMember:
    return _moderate(
        actor=actor,
        community_id=community_id,
        member_id=member_id,
        target=S.REJECTED,
        sources=(S.PENDING,),
    )


def remove(*, actor: User, community_id: UUID, member_id: UUID) -> CommunityMember:
    """Remove a member, or withdraw an invitation that has not been answered."""
    return _moderate(
        actor=actor,
        community_id=community_id,
        member_id=member_id,
        target=S.REMOVED,
        sources=(S.ACTIVE, S.INVITED),
    )


def ban(*, actor: User, community_id: UUID, member_id: UUID) -> CommunityMember:
    return _moderate(
        actor=actor,
        community_id=community_id,
        member_id=member_id,
        target=S.BANNED,
        sources=(S.ACTIVE,),
    )


def unban(*, actor: User, community_id: UUID, member_id: UUID) -> CommunityMember:
    """Lift a ban. The person is not a member again until they join."""
    with transaction.atomic():
        community = _lock(community_id)
        _require_active(community)
        member = _member(community, member_id)
        if member.status != S.BANNED:
            raise InvalidTransition("This person is not banned.")
        _move(member, S.REMOVED, actor=_actor(community, actor), by=actor, community=community)
        return member


def invite(*, actor: User, community_id: UUID, user_id: UUID) -> CommunityMember:
    """Invite a user. Only people whose profile the actor can open can be invited, so this
    cannot be used to find out who has an account."""
    if actor.pk == user_id:
        raise BusinessRuleViolation("You cannot invite yourself.", code="cannot_invite_self")
    invitee = get_visible_user(actor, user_id)
    with transaction.atomic():
        community = _lock(community_id)
        _require_active(community)
        acting = _actor(community, actor)
        if not policies.can_manage(acting):
            raise PermissionDenied()

        member = _row(community, invitee.pk)
        if member is None:
            member = CommunityMember.objects.create(
                community=community, user=invitee, status=S.INVITED, invited_by=actor
            )
            _record_change(member, by=actor, previous=None, community=community)
        elif member.status == S.INVITED:
            return member
        elif member.status == S.ACTIVE:
            raise Conflict("This person is already a member.", code="already_member")
        elif member.status == S.PENDING:
            raise Conflict(
                "This person has asked to join. Approve their request instead.",
                code="request_pending",
            )
        elif member.status == S.BANNED:
            raise Conflict("This person is banned. Lift the ban first.", code="banned")
        else:
            member.invited_by = actor
            _move(member, S.INVITED, actor=acting, by=actor, community=community)
        transaction.on_commit(partial(enqueue, tasks.send_invitation_email, str(member.pk)))
        return member


def change_role(
    *, actor: User, community_id: UUID, member_id: UUID, role: CommunityRole
) -> CommunityMember:
    with transaction.atomic():
        community = _lock(community_id)
        _require_active(community)
        member = _member(community, member_id)
        if not policies.can_change_role(_actor(community, actor), member, role):
            raise PermissionDenied()
        previous = member.role
        if previous == role:
            return member
        if _is_active_owner(member):
            _guard_last_owner(community)
        member.role = role
        member.save(update_fields=["role", "updated_at"])
        record(
            action="community.role_changed",
            target=member,
            actor=actor,
            community_id=community.pk,
            metadata={"from": previous, "to": role},
        )
        return member
