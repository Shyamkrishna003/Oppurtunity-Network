"""Read queries for applications. Views load objects only through these."""

from dataclasses import dataclass
from uuid import UUID

from django.db.models import Count, Q, QuerySet
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from applications import policies
from applications.models import Application, ApplicationStatus, ApplicationStatusHistory
from applications.policies import Actor, Barrier
from opportunities import policies as opportunity_policies
from opportunities import selectors as opportunities
from opportunities.models import Opportunity, OpportunityType
from opportunities.selectors import Viewer
from organizations.models import MembershipStatus, OrganizationMember
from users.models import User
from users.selectors import is_blocked_either_way

# An organization has a handful of people who handle applications; this only bounds the
# damage if one ever has hundreds.
MAX_MANAGERS_NOTIFIED = 50


def visible_to(user: User) -> QuerySet[Application]:
    """Applications the user may see: their own, and those to jobs they manage. Nobody else
    can, platform staff included: an application is between the applicant and the employer."""
    managed = Opportunity.objects.filter(opportunities.managed_by(user))
    return Application.objects.filter(Q(applicant=user) | Q(opportunity__in=managed))


def _with_details(queryset: QuerySet[Application]) -> QuerySet[Application]:
    return queryset.select_related("opportunity__organization", "applicant__profile")


def is_manager(user: User, opportunity: Opportunity) -> bool:
    membership = opportunities.get_membership(user, opportunity.organization_id)
    return opportunity_policies.can_manage(user, opportunity, membership)


def actor_for(user: User, application: Application) -> Actor:
    return Actor(
        is_applicant=application.applicant_id == user.pk,
        is_manager=is_manager(user, application.opportunity),
    )


def get_application(user: User, application_id: UUID) -> Application:
    """The application if the user may see it, else 404: someone else's application and one
    that does not exist look the same."""
    application = _with_details(visible_to(user).filter(pk=application_id)).first()
    if application is None:
        raise Http404
    return application


def list_mine(user: User, status: str = "") -> QuerySet[Application]:
    """What the user applied to, newest first, whatever became of the job since."""
    applications = Application.objects.filter(applicant=user)
    if status:
        applications = applications.filter(status=status)
    return _with_details(applications)


def history_of(application: Application) -> QuerySet[ApplicationStatusHistory]:
    return application.history.select_related("actor__profile").order_by("created_at", "id")


def get_managed_job(user: User, opportunity_id: UUID) -> Opportunity:
    """The job, for someone about to look at its applications.

    404 if they cannot see it at all or it is not a job; 403 if they can see it but do not
    manage it, which reveals nothing they could not already see.
    """
    opportunity = opportunities.get_opportunity(user, opportunity_id)
    if opportunity.type != OpportunityType.JOB:
        raise Http404
    if not is_manager(user, opportunity):
        raise PermissionDenied()
    return opportunity


def list_for_job(opportunity: Opportunity, status: str = "") -> QuerySet[Application]:
    """A job's applications, for its managers. The caller has established that they are one."""
    applications = Application.objects.filter(opportunity=opportunity)
    if status:
        applications = applications.filter(status=status)
    return applications.select_related("applicant__profile")


def stage_counts(opportunity: Opportunity) -> dict[str, int]:
    """How many applications the job has in each status, zeros included."""
    counted = dict(
        Application.objects.filter(opportunity=opportunity)
        .values_list("status")
        .annotate(total=Count("id"))
    )
    return {status: counted.get(status, 0) for status in ApplicationStatus.values}


def managers_of(opportunity: Opportunity) -> list[User]:
    """The people who handle applications to this job: its poster, or the organization's
    owners, admins and recruiters."""
    if opportunity.organization_id is None:
        return [opportunity.creator]
    memberships = (
        OrganizationMember.objects.filter(
            organization_id=opportunity.organization_id,
            status=MembershipStatus.ACTIVE,
            role__in=opportunity_policies.POSTING_ROLES,
        )
        .select_related("user")
        .order_by("joined_at")[:MAX_MANAGERS_NOTIFIED]
    )
    return [membership.user for membership in memberships]


def barrier_to_applying(user: User, opportunity: Opportunity) -> Barrier | None:
    """What stops the user applying to this job (which they can see), if anything."""
    return policies.barrier_to_applying(
        opportunity,
        is_manager=is_manager(user, opportunity),
        # Only a personal job has one person on the other side to have blocked.
        is_blocked=opportunity.organization_id is None
        and is_blocked_either_way(user, opportunity.creator),
        now=timezone.now(),
    )


@dataclass(frozen=True)
class ApplyingState:
    """What the opportunity page needs to know about the viewer and applying."""

    can_apply: bool
    application: Application | None


def applying_state(viewer: Viewer, opportunity: Opportunity) -> ApplyingState:
    if not viewer.is_authenticated or opportunity.type != OpportunityType.JOB:
        return ApplyingState(can_apply=False, application=None)
    application = Application.objects.filter(opportunity=opportunity, applicant=viewer).first()
    return ApplyingState(
        can_apply=application is None and barrier_to_applying(viewer, opportunity) is None,
        application=application,
    )
