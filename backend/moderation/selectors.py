"""Read queries for reports and moderation actions."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import models
from django.db.models import QuerySet
from django.http import Http404

from applications.selectors import managers_of
from communities import selectors as communities
from communities.models import Community, CommunityRole, CommunityStatus, MemberStatus
from moderation.models import ModerationAction, Report, TargetType, target_field
from moderation.policies import IN_PROGRESS
from opportunities import policies as opportunity_policies
from opportunities import selectors as opportunities
from opportunities.models import (
    DistributionStatus,
    ModerationStatus,
    Opportunity,
    OpportunityCommunity,
)
from organizations import selectors as organizations
from organizations.models import (
    MembershipStatus,
    Organization,
    OrganizationRole,
    OrganizationStatus,
    VerificationStatus,
)
from users.models import User
from users.selectors import get_visible_user

# An organization or a community has few owners; this only guards against a strange one.
MAX_OWNERS_NOTIFIED = 20

_TARGETS = ("target_user__profile", "target_organization", "target_community", "target_opportunity")


def find_target(viewer: User, target_type: TargetType, target_id: UUID) -> models.Model:
    """The thing being reported, if the viewer can see it; else 404. Nobody can report, or
    learn of, something they could not have looked at."""
    match target_type:
        case TargetType.USER:
            return get_visible_user(viewer, target_id)
        case TargetType.ORGANIZATION:
            return organizations.get_organization(viewer, target_id)
        case TargetType.COMMUNITY:
            return communities.get_community(viewer, target_id)
        case TargetType.OPPORTUNITY:
            return opportunities.get_opportunity(viewer, target_id)
    raise Http404


def is_own(user: User, target: models.Model) -> bool:
    """Whether the target is the user, or an opportunity they manage."""
    if isinstance(target, User):
        return target.pk == user.pk
    if isinstance(target, Opportunity):
        membership = opportunities.get_membership(user, target.organization_id)
        return opportunity_policies.can_manage(user, target, membership)
    return False


@dataclass(frozen=True)
class Described:
    """A target in words, for a list: what it is called and where its page is."""

    type: str
    id: UUID
    label: str
    url: str


def describe(target: models.Model) -> Described:
    if isinstance(target, User):
        return Described(
            TargetType.USER, target.pk, target.profile.display_name, f"/users/{target.pk}"
        )
    if isinstance(target, Organization):
        return Described(
            TargetType.ORGANIZATION, target.pk, target.name, f"/organizations/{target.pk}"
        )
    if isinstance(target, Community):
        return Described(TargetType.COMMUNITY, target.pk, target.name, f"/communities/{target.pk}")
    if isinstance(target, Opportunity):
        return Described(
            TargetType.OPPORTUNITY, target.pk, target.title, f"/opportunities/{target.pk}"
        )
    raise TypeError(f"Not something that can be reported: {type(target).__name__}")


def list_mine(user: User) -> QuerySet[Report]:
    """The user's own reports, with where each stands."""
    return Report.objects.filter(reporter=user).select_related(*_TARGETS)


def queue(
    status: str = "", target_type: str = "", *, community_id: UUID | None = None
) -> QuerySet[Report]:
    """Reports for the platform's moderators, or with ``community_id`` for that community's.
    Each report is in exactly one of those queues. The caller has established that the
    reader may read the one asked for."""
    reports = Report.objects.filter(scope_community_id=community_id).select_related(
        "reporter__profile", "assigned_to__profile", *_TARGETS
    )
    if status:
        reports = reports.filter(status=status)
    if target_type:
        reports = reports.filter(target_type=target_type)
    return reports


def get_report(report_id: UUID, *, community_id: UUID | None = None) -> Report:
    report = queue(community_id=community_id).filter(pk=report_id).first()
    if report is None:
        raise Http404
    return report


def is_shown_in(community_id: UUID, opportunity_id: UUID | None) -> bool:
    """Whether the community currently shows the opportunity."""
    if opportunity_id is None:
        return False
    return OpportunityCommunity.objects.filter(
        community_id=community_id,
        opportunity_id=opportunity_id,
        status=DistributionStatus.APPROVED,
    ).exists()


def about(target_type: str, target_id: object) -> dict[str, object]:
    """The filter that picks out everything about one target."""
    return {"target_type": target_type, f"{target_field(target_type)}_id": target_id}


def in_progress_on(report: Report) -> int:
    """How many reports about the same thing are still waiting, this one included. For a
    community's report, only those sent to that community: the rest are not theirs to know."""
    waiting = Report.objects.filter(
        **about(report.target_type, report.target_id), status__in=IN_PROGRESS
    )
    if report.scope_community_id is not None:
        waiting = waiting.filter(scope_community_id=report.scope_community_id)
    return waiting.count()


_MODELS: dict[TargetType, type[models.Model]] = {
    TargetType.USER: User,
    TargetType.ORGANIZATION: Organization,
    TargetType.COMMUNITY: Community,
    TargetType.OPPORTUNITY: Opportunity,
}


def load_target(target_type: TargetType, target_id: UUID) -> models.Model:
    """Any target, for a moderator: nothing is hidden from them, and a suspended account or a
    removed opportunity is exactly what they need to be able to open."""
    queryset = _MODELS[target_type].objects.filter(pk=target_id)  # type: ignore[attr-defined]
    if target_type == TargetType.USER:
        queryset = queryset.select_related("profile")
    target = queryset.first()
    if target is None:
        raise Http404
    return target  # type: ignore[no-any-return]


def standing(target: models.Model) -> list[str]:
    """How the target stands with the moderators, in words. Empty when nothing is in force."""
    notes: list[str] = []

    def lasting(until: datetime) -> str:
        return "until lifted" if until.year >= 9999 else f"until {until.date().isoformat()}"

    if isinstance(target, User):
        if target.is_suspended and target.suspended_until:
            notes.append(f"Suspended {lasting(target.suspended_until)}")
        if target.is_posting_restricted and target.posting_restricted_until:
            notes.append(f"Cannot post {lasting(target.posting_restricted_until)}")
        if not target.is_active:
            notes.append("Deactivated")
    elif isinstance(target, Organization):
        if target.status == OrganizationStatus.SUSPENDED:
            notes.append("Suspended")
        if target.verification_status == VerificationStatus.VERIFIED:
            notes.append("Verified")
    elif isinstance(target, Community):
        if target.status == CommunityStatus.SUSPENDED:
            notes.append("Suspended")
    elif isinstance(target, Opportunity) and target.moderation_status != ModerationStatus.VISIBLE:
        notes.append(ModerationStatus(target.moderation_status).label)
    return notes


def responsible_for(target: models.Model) -> list[User]:
    """Who is told when a moderator acts on the target: the person, or the people who run
    the thing. A small, bounded set."""
    if isinstance(target, User):
        return [target]
    if isinstance(target, Opportunity):
        return managers_of(target)
    if isinstance(target, Organization):
        owners = User.objects.filter(
            organization_memberships__organization=target,
            organization_memberships__status=MembershipStatus.ACTIVE,
            organization_memberships__role=OrganizationRole.OWNER,
        )
    elif isinstance(target, Community):
        owners = User.objects.filter(
            community_memberships__community=target,
            community_memberships__status=MemberStatus.ACTIVE,
            community_memberships__role=CommunityRole.OWNER,
        )
    else:
        return []
    return list(owners.filter(is_active=True)[:MAX_OWNERS_NOTIFIED])


def actions_about(target_type: str, target_id: object) -> QuerySet[ModerationAction]:
    """Everything moderators have done to a target, newest first."""
    return (
        ModerationAction.objects.filter(**about(target_type, target_id))
        .select_related("actor__profile")
        .order_by("-created_at", "-id")
    )


def actions_on(report: Report) -> QuerySet[ModerationAction]:
    """Everything moderators have done to the report's target, newest first."""
    return (
        ModerationAction.objects.filter(**about(report.target_type, report.target_id))
        .select_related("actor__profile")
        .order_by("-created_at", "-id")
    )
