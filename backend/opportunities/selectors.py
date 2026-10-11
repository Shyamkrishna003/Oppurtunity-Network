"""Read queries for opportunities. Views load objects only through these."""

from dataclasses import dataclass
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.http import Http404

from communities.models import Community, CommunityMember, CommunityStatus, MemberStatus
from communities.policies import actor_for
from communities.selectors import visible_to as visible_communities
from opportunities.distribution_policies import share_outcome
from opportunities.models import (
    DistributionStatus,
    ModerationStatus,
    Opportunity,
    OpportunityCommunity,
    OpportunityStatus,
    OpportunityVisibility,
    SavedOpportunity,
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


@dataclass(frozen=True)
class ShareOption:
    """One of the manager's communities, and what sharing into it would do."""

    community: Community
    # The existing share's status, if the opportunity is already there.
    current: str | None
    # What sharing would lead to (approved at once, or pending review); None if not allowed.
    outcome: str | None


def list_shares(opportunity: Opportunity) -> QuerySet[OpportunityCommunity]:
    """Every community the opportunity was offered to, for its managers."""
    return OpportunityCommunity.objects.filter(opportunity=opportunity).select_related("community")


def share_options(user: User, opportunity: Opportunity) -> list[ShareOption]:
    """The communities the user is an active member of, each with what sharing would do."""
    memberships = (
        CommunityMember.objects.filter(
            user=user, status=MemberStatus.ACTIVE, community__status=CommunityStatus.ACTIVE
        )
        .select_related("community")
        .order_by("community__name")
    )
    existing = dict(
        OpportunityCommunity.objects.filter(opportunity=opportunity).values_list(
            "community_id", "status"
        )
    )
    return [
        ShareOption(
            community=membership.community,
            current=existing.get(membership.community_id),
            outcome=share_outcome(membership.community, actor_for(user.pk, membership)),
        )
        for membership in memberships
    ]


def communities_showing(viewer: Viewer, opportunity: Opportunity) -> QuerySet[Community]:
    """Communities where the opportunity is approved, limited to those the viewer may see:
    a private community's name is not revealed through an opportunity."""
    return visible_communities(viewer).filter(
        distributions__opportunity=opportunity,
        distributions__status=DistributionStatus.APPROVED,
        status=CommunityStatus.ACTIVE,
    )


def _share_details(queryset: QuerySet[OpportunityCommunity]) -> QuerySet[OpportunityCommunity]:
    return queryset.select_related(
        "opportunity__organization",
        "opportunity__creator__profile",
        "opportunity__job",
        "submitted_by__profile",
    ).prefetch_related("opportunity__skills")


def community_opportunities(
    viewer: Viewer, community: Community, *, featured_only: bool = False
) -> QuerySet[OpportunityCommunity]:
    """Open opportunities a community shows, newest share first.

    Approval by the community is necessary but not sufficient: the viewer must also be
    allowed to see the opportunity itself, so the global rule is applied as well.
    """
    shares = OpportunityCommunity.objects.filter(
        community=community,
        status=DistributionStatus.APPROVED,
        opportunity__status=OpportunityStatus.PUBLISHED,
        opportunity__in=visible_to(viewer),
    )
    if featured_only:
        shares = shares.filter(is_featured=True)
    return _share_details(shares)


def community_queue(
    community: Community, status: DistributionStatus
) -> QuerySet[OpportunityCommunity]:
    """Shares in one state, for the community's moderators."""
    return _share_details(OpportunityCommunity.objects.filter(community=community, status=status))


def list_saved(user: User) -> QuerySet[SavedOpportunity]:
    """What the user saved, most recently saved first, in whatever state it is now.

    Something saved and later hidden, archived or restricted drops out: saving it does not
    keep it visible.
    """
    return (
        SavedOpportunity.objects.filter(user=user, opportunity__in=visible_to(user))
        .select_related(
            "opportunity__organization", "opportunity__creator__profile", "opportunity__job"
        )
        .prefetch_related("opportunity__skills")
    )


def is_saved(viewer: Viewer, opportunity: Opportunity) -> bool:
    return (
        viewer.is_authenticated
        and SavedOpportunity.objects.filter(user=viewer, opportunity=opportunity).exists()
    )


def list_managed(user: User, status: str = "") -> QuerySet[Opportunity]:
    """Opportunities the user manages, in any state, for their own dashboard."""
    opportunities = Opportunity.objects.filter(managed_by(user))
    if status:
        opportunities = opportunities.filter(status=status)
    return with_details(opportunities)
