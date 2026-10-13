"""Read queries for reports and moderation actions."""

from dataclasses import dataclass
from uuid import UUID

from django.db import models
from django.db.models import QuerySet
from django.http import Http404

from communities import selectors as communities
from communities.models import Community
from moderation.models import ModerationAction, Report, TargetType, target_field
from moderation.policies import IN_PROGRESS
from opportunities import policies as opportunity_policies
from opportunities import selectors as opportunities
from opportunities.models import Opportunity
from organizations import selectors as organizations
from organizations.models import Organization
from users.models import User
from users.selectors import get_visible_user

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


def queue(status: str = "", target_type: str = "") -> QuerySet[Report]:
    """Reports for the moderators. The caller has established that the reader is one."""
    reports = Report.objects.select_related("reporter__profile", "assigned_to__profile", *_TARGETS)
    if status:
        reports = reports.filter(status=status)
    if target_type:
        reports = reports.filter(target_type=target_type)
    return reports


def get_report(report_id: UUID) -> Report:
    report = queue().filter(pk=report_id).first()
    if report is None:
        raise Http404
    return report


def about(target_type: str, target_id: object) -> dict[str, object]:
    """The filter that picks out everything about one target."""
    return {"target_type": target_type, f"{target_field(target_type)}_id": target_id}


def in_progress_on(report: Report) -> int:
    """How many reports about the same thing are still waiting, this one included."""
    return Report.objects.filter(
        **about(report.target_type, report.target_id), status__in=IN_PROGRESS
    ).count()


def actions_on(report: Report) -> QuerySet[ModerationAction]:
    """Everything moderators have done to the report's target, newest first."""
    return (
        ModerationAction.objects.filter(**about(report.target_type, report.target_id))
        .select_related("actor__profile")
        .order_by("-created_at", "-id")
    )
