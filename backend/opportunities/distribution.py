"""Sharing opportunities with communities: every write to ``OpportunityCommunity``."""

from collections.abc import Iterable
from uuid import UUID

from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from audit.services import record
from common.errors import BusinessRuleViolation, Conflict, FieldErrors, InvalidTransition
from communities.models import Community, CommunityMember, CommunityStatus
from communities.policies import Actor as CommunityActor
from communities.policies import actor_for, is_member
from communities.selectors import reviewers
from notifications.models import NotificationType
from notifications.services import notify, notify_each
from opportunities import distribution_policies as policies
from opportunities.distribution_policies import DISTRIBUTION, Reviewer, Submitter
from opportunities.models import (
    DistributionStatus,
    Opportunity,
    OpportunityCommunity,
    OpportunityStatus,
)
from opportunities.services import lock_opportunity, require_manager
from users.models import User

MAX_COMMUNITIES_PER_SHARE = 10
S = DistributionStatus

_NOT_A_MEMBER = "You are not a member of this community."
_NOT_ALLOWED = "This community does not let you share opportunities."
_REMOVED = "This community has removed this opportunity."
_MEMBER_GONE = "The member who shared this is no longer in the community."


def _community_actor(community: Community, user: User) -> CommunityActor:
    membership = CommunityMember.objects.filter(community=community, user=user).first()
    return actor_for(user.pk, membership)


def _audit(
    action: str,
    share: OpportunityCommunity,
    *,
    actor: User | None,
    opportunity: Opportunity,
    **metadata: str | bool | None,
) -> None:
    record(
        action=action,
        target=share,
        actor=actor,
        organization_id=opportunity.organization_id,
        community_id=share.community_id,
        metadata={"opportunity_id": str(opportunity.pk), **metadata},
    )


def _about(
    share: OpportunityCommunity, community: Community, opportunity: Opportunity
) -> dict[str, str]:
    return {
        "community_id": str(community.pk),
        "community_name": community.name,
        "opportunity_id": str(opportunity.pk),
        "opportunity_title": opportunity.title,
    }


def _notify_reviewers(
    share: OpportunityCommunity, community: Community, opportunity: Opportunity, *, by: User
) -> None:
    """Something is waiting for the community's decision. Nothing to say if it went
    straight through."""
    if share.status != S.PENDING:
        return
    notify_each(
        reviewers(community),
        type=NotificationType.SHARE_SUBMITTED,
        target=share,
        actor=by,
        payload={
            **_about(share, community, opportunity),
            "person_name": by.profile.display_name,
        },
    )


_DECISION_NOTICES = {
    S.APPROVED: NotificationType.SHARE_APPROVED,
    S.REJECTED: NotificationType.SHARE_REJECTED,
    S.REMOVED: NotificationType.SHARE_REMOVED,
}


def _notify_submitter(share: OpportunityCommunity, *, by: User) -> None:
    """Tell whoever shared it what the community decided."""
    if share.submitted_by is None:
        return
    payload = _about(share, share.community, share.opportunity)
    if share.status == S.REJECTED:
        payload["reason"] = share.rejection_reason
    notify(
        recipient=share.submitted_by,
        type=_DECISION_NOTICES[DistributionStatus(share.status)],
        target=share,
        actor=by,
        payload=payload,
    )


# --- The opportunity's side -------------------------------------------------------------


def share(
    *, actor: User, opportunity_id: UUID, community_ids: Iterable[UUID]
) -> list[OpportunityCommunity]:
    """Offer a published opportunity to communities the actor belongs to.

    All or nothing: if any community cannot be shared with, none is, and the error says why
    for each one. Sharing again with a community that already has it changes nothing.
    """
    wanted = list(dict.fromkeys(community_ids))
    if not wanted or len(wanted) > MAX_COMMUNITIES_PER_SHARE:
        message = f"Choose between 1 and {MAX_COMMUNITIES_PER_SHARE} communities."
        raise BusinessRuleViolation(
            message, code="invalid_selection", errors={"community_ids": [message]}
        )

    with transaction.atomic():
        opportunity = lock_opportunity(opportunity_id)
        require_manager(actor, opportunity)
        if opportunity.status != OpportunityStatus.PUBLISHED:
            raise BusinessRuleViolation(
                "Publish the opportunity before sharing it with communities.",
                code="not_published",
            )
        # Locked in a fixed order, so two people sharing with overlapping sets cannot deadlock.
        communities = {
            community.pk: community
            for community in Community.objects.select_for_update()
            .filter(pk__in=wanted, status=CommunityStatus.ACTIVE)
            .order_by("pk")
        }

        errors: FieldErrors = {}
        shares: list[OpportunityCommunity] = []
        for community_id in wanted:
            community = communities.get(community_id)
            # A community the actor cannot see is answered like one they are not in.
            acting = _community_actor(community, actor) if community else None
            if community is None or acting is None or not is_member(acting):
                errors[str(community_id)] = [_NOT_A_MEMBER]
                continue
            outcome = policies.share_outcome(community, acting)
            if outcome is None:
                errors[str(community_id)] = [_NOT_ALLOWED]
                continue

            existing = OpportunityCommunity.objects.filter(
                opportunity=opportunity, community=community
            ).first()
            if existing is None:
                existing = OpportunityCommunity.objects.create(
                    opportunity=opportunity, community=community, status=outcome, submitted_by=actor
                )
                _audit(
                    "opportunity.shared",
                    existing,
                    actor=actor,
                    opportunity=opportunity,
                    status=outcome,
                )
                _notify_reviewers(existing, community, opportunity, by=actor)
            elif existing.status == S.REMOVED:
                errors[str(community_id)] = [_REMOVED]
                continue
            elif existing.status == S.REJECTED:
                DISTRIBUTION.apply(existing, outcome, actor=Submitter())
                existing.submitted_by = actor
                existing.reviewed_by = None
                existing.reviewed_at = None
                existing.rejection_reason = ""
                existing.save()
                _audit(
                    "opportunity.shared",
                    existing,
                    actor=actor,
                    opportunity=opportunity,
                    status=outcome,
                )
                _notify_reviewers(existing, community, opportunity, by=actor)
            shares.append(existing)

        if errors:
            raise BusinessRuleViolation(
                "This opportunity cannot be shared with every community you chose.",
                code="cannot_share",
                errors=errors,
            )
        return shares


def withdraw(*, actor: User, opportunity_id: UUID, community_id: UUID) -> None:
    """Take a share back. Not possible once the community itself has removed it: that
    decision stays on record."""
    with transaction.atomic():
        opportunity = lock_opportunity(opportunity_id)
        require_manager(actor, opportunity)
        existing = (
            OpportunityCommunity.objects.select_for_update()
            .filter(opportunity=opportunity, community_id=community_id)
            .first()
        )
        if existing is None:
            raise Http404
        if existing.status == S.REMOVED:
            raise Conflict(_REMOVED, code="removed_by_community")
        _audit(
            "opportunity.share_withdrawn",
            existing,
            actor=actor,
            opportunity=opportunity,
            status=existing.status,
        )
        existing.delete()


# --- The community's side ---------------------------------------------------------------


def _reviewed_share(
    actor: User, community_id: UUID, share_id: UUID
) -> tuple[OpportunityCommunity, Reviewer]:
    """Lock the community and the share, and establish that the actor may review it.

    Locking the community serialises this with role changes, so someone being demoted at the
    same moment cannot slip a decision through.
    """
    community = Community.objects.select_for_update().filter(pk=community_id).first()
    if community is None:
        raise Http404
    if community.status != CommunityStatus.ACTIVE:
        raise BusinessRuleViolation("This community is suspended.", code="community_suspended")
    acting = _community_actor(community, actor)
    if acting.role is None or not policies.can_review(acting):
        raise PermissionDenied()
    existing = (
        OpportunityCommunity.objects.select_for_update(of=("self",))
        .select_related("opportunity", "community", "submitted_by")
        .filter(pk=share_id, community=community)
        .first()
    )
    if existing is None:
        raise Http404
    return existing, Reviewer(acting.role)


def review(
    *,
    actor: User,
    community_id: UUID,
    share_id: UUID,
    decision: DistributionStatus,
    reason: str = "",
) -> OpportunityCommunity:
    """Approve or reject a pending share, or remove one that was approved."""
    with transaction.atomic():
        existing, reviewer = _reviewed_share(actor, community_id, share_id)
        previous = existing.status
        if not DISTRIBUTION.apply(existing, decision, actor=reviewer):
            return existing  # already decided this way: a repeated request
        existing.reviewed_by = actor
        existing.reviewed_at = timezone.now()
        existing.rejection_reason = reason if decision == S.REJECTED else ""
        if decision != S.APPROVED:
            existing.is_featured = False
            existing.featured_until = None
        existing.save()
        _audit(
            "opportunity.share_reviewed",
            existing,
            actor=actor,
            opportunity=existing.opportunity,
            **{"from": previous, "to": decision},
        )
        _notify_submitter(existing, by=actor)
        return existing


def set_featured(
    *, actor: User, community_id: UUID, share_id: UUID, featured: bool
) -> OpportunityCommunity:
    """Pin an approved opportunity to the top of the community's list, or unpin it."""
    with transaction.atomic():
        existing, _ = _reviewed_share(actor, community_id, share_id)
        if existing.status != S.APPROVED:
            raise InvalidTransition("Only an approved opportunity can be featured.")
        if existing.is_featured != featured:
            existing.is_featured = featured
            existing.save(update_fields=["is_featured", "updated_at"])
            _audit(
                "opportunity.share_featured",
                existing,
                actor=actor,
                opportunity=existing.opportunity,
                featured=featured,
            )
        return existing


def reject_pending_from(*, community_id: UUID, user_id: UUID, by: User) -> int:
    """Reject what a person had waiting for review in a community they were just removed or
    banned from. Call inside the transaction that removes them. Returns how many."""
    pending = (
        OpportunityCommunity.objects.select_for_update(of=("self",))
        .select_related("opportunity")
        .filter(community_id=community_id, submitted_by_id=user_id, status=S.PENDING)
    )
    now = timezone.now()
    count = 0
    for existing in pending:
        existing.status = S.REJECTED
        existing.reviewed_by = by
        existing.reviewed_at = now
        existing.rejection_reason = _MEMBER_GONE
        existing.save()
        _audit(
            "opportunity.share_reviewed",
            existing,
            actor=by,
            opportunity=existing.opportunity,
            **{"from": S.PENDING, "to": S.REJECTED},
        )
        count += 1
    return count
