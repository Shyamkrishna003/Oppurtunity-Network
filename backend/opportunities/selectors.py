"""Read queries for opportunities. Views load objects only through these."""

from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.http import Http404

from communities.models import CommunityMember, MemberStatus
from opportunities.models import (
    DistributionStatus,
    ModerationStatus,
    Opportunity,
    OpportunityCommunity,
    OpportunityStatus,
    OpportunityVisibility,
)
from opportunities.policies import POSTING_ROLES
from organizations.models import MembershipStatus, OrganizationMember
from users.models import User
from users.policies import is_platform_staff

Viewer = User | AnonymousUser

# States in which people other than the managers may see an opportunity. Drafts are private
# to their managers, and archived ones are out of every public view.
_PUBLIC_STATES = (
    OpportunityStatus.PUBLISHED,
    OpportunityStatus.CLOSED,
    OpportunityStatus.EXPIRED,
)


def _active_memberships(user: User) -> QuerySet[OrganizationMember]:
    return OrganizationMember.objects.filter(user=user, status=MembershipStatus.ACTIVE)


def get_membership(user: Viewer, organization_id: UUID | None) -> OrganizationMember | None:
    """The user's active membership of an organization, if any."""
    if organization_id is None or not user.is_authenticated:
        return None
    return _active_memberships(user).filter(organization_id=organization_id).first()


def managed_by(user: User) -> Q:
    """Opportunities the user manages: their own personal ones, and those of organizations
    where they are an owner, admin or recruiter."""
    posting = _active_memberships(user).filter(
        organization=OuterRef("organization"), role__in=POSTING_ROLES
    )
    return Q(organization__isnull=True, creator=user) | Q(Exists(posting))


def visible_to(viewer: Viewer) -> QuerySet[Opportunity]:
    """Every opportunity the viewer may see. The single definition of that rule; lists and
    detail pages both go through it, so nothing has to filter in Python."""
    if viewer.is_authenticated and is_platform_staff(viewer):
        return Opportunity.objects.all()

    shown = Q(status__in=_PUBLIC_STATES, moderation_status=ModerationStatus.VISIBLE)
    public = Q(visibility=OpportunityVisibility.PUBLIC)
    if not viewer.is_authenticated:
        return Opportunity.objects.filter(shown & public)

    in_my_community = OpportunityCommunity.objects.filter(
        opportunity=OuterRef("pk"),
        status=DistributionStatus.APPROVED,
        community__in=CommunityMember.objects.filter(
            user=viewer, status=MemberStatus.ACTIVE
        ).values("community"),
    )
    in_my_organization = _active_memberships(viewer).filter(organization=OuterRef("organization"))
    audience = (
        public
        | (Q(visibility=OpportunityVisibility.COMMUNITY) & Exists(in_my_community))
        | (Q(visibility=OpportunityVisibility.ORGANIZATION) & Exists(in_my_organization))
    )
    return Opportunity.objects.filter((shown & audience) | managed_by(viewer))


def with_details(queryset: QuerySet[Opportunity]) -> QuerySet[Opportunity]:
    """Everything a serialized opportunity needs, in a fixed number of queries."""
    return queryset.select_related("organization", "creator__profile", "job").prefetch_related(
        "skills"
    )


def get_opportunity(viewer: Viewer, opportunity_id: UUID) -> Opportunity:
    """The opportunity if the viewer may see it, else 404: a draft, a hidden one and one that
    does not exist look the same from outside."""
    opportunity = with_details(visible_to(viewer).filter(pk=opportunity_id)).first()
    if opportunity is None:
        raise Http404
    return opportunity


def list_managed(user: User, status: str = "") -> QuerySet[Opportunity]:
    """Opportunities the user manages, in any state, for their own dashboard."""
    opportunities = Opportunity.objects.filter(managed_by(user))
    if status:
        opportunities = opportunities.filter(status=status)
    return with_details(opportunities)
