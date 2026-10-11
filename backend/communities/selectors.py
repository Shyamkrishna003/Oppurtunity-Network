"""Read queries for communities. Views load objects only through these."""

from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.db.models import Count, Exists, OuterRef, Q, QuerySet
from django.http import Http404

from communities.models import (
    Community,
    CommunityMember,
    CommunityStatus,
    CommunityVisibility,
    MemberStatus,
)
from users.models import User
from users.policies import is_platform_staff

Viewer = User | AnonymousUser

# Being invited is enough to see a private community: you must be able to look before joining.
_INSIDE = (MemberStatus.ACTIVE, MemberStatus.INVITED)
# What a person sees under "my communities".
_MINE = (MemberStatus.ACTIVE, MemberStatus.INVITED, MemberStatus.PENDING)


def get_membership(viewer: Viewer, community: Community) -> CommunityMember | None:
    """The viewer's membership row in any state, if there is one."""
    if not viewer.is_authenticated:
        return None
    return CommunityMember.objects.filter(community=community, user=viewer).first()


def _with_member_count(queryset: QuerySet[Community]) -> QuerySet[Community]:
    return queryset.annotate(
        member_count=Count("memberships", filter=Q(memberships__status=MemberStatus.ACTIVE))
    )


def _visible_to(viewer: Viewer) -> QuerySet[Community]:
    """Every community the viewer may know exists. The single definition of that rule."""
    if viewer.is_authenticated and is_platform_staff(viewer):
        return Community.objects.all()
    public = Q(status=CommunityStatus.ACTIVE, visibility=CommunityVisibility.PUBLIC)
    if not viewer.is_authenticated:
        return Community.objects.filter(public)
    inside = CommunityMember.objects.filter(
        community=OuterRef("pk"), user=viewer, status__in=_INSIDE
    )
    # Members also keep sight of their community while it is private or suspended.
    return Community.objects.filter(public | Exists(inside))


def list_communities(viewer: Viewer, query: str = "", category: str = "") -> QuerySet[Community]:
    communities = _visible_to(viewer).filter(status=CommunityStatus.ACTIVE)
    query = query.strip()
    if query:
        communities = communities.filter(Q(name__icontains=query) | Q(name__trigram_similar=query))
    if category:
        communities = communities.filter(category__iexact=category.strip())
    return _with_member_count(communities)


def get_community(viewer: Viewer, community_id: UUID) -> Community:
    """The community if the viewer may see it, else 404: a private community and one that
    does not exist look the same from outside."""
    community = _with_member_count(_visible_to(viewer).filter(pk=community_id)).first()
    if community is None:
        raise Http404
    return community


def list_user_communities(user: User) -> QuerySet[CommunityMember]:
    """The user's memberships, invitations and pending requests, for navigation."""
    return (
        CommunityMember.objects.filter(user=user, status__in=_MINE)
        .select_related("community")
        .order_by("community__name")
    )


def list_members(community: Community, status: MemberStatus) -> QuerySet[CommunityMember]:
    return CommunityMember.objects.filter(
        community=community, status=status, user__is_active=True
    ).select_related("user__profile")


def share_a_community(first: User, second: User) -> bool:
    """Whether both users are active members of at least one common community."""
    return CommunityMember.objects.filter(
        user=first,
        status=MemberStatus.ACTIVE,
        community__in=CommunityMember.objects.filter(
            user=second, status=MemberStatus.ACTIVE
        ).values("community"),
    ).exists()
