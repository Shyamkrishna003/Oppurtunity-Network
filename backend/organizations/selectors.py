"""Read queries for organizations. Views load objects only through these."""

from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.db.models import Count, Q, QuerySet
from django.http import Http404

from organizations.models import (
    InvitationStatus,
    MembershipStatus,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    OrganizationStatus,
)
from users.models import User
from users.policies import is_platform_staff

Viewer = User | AnonymousUser


def get_membership(user: Viewer, organization: Organization) -> OrganizationMember | None:
    """The user's active membership of the organization, if any."""
    if not user.is_authenticated:
        return None
    return OrganizationMember.objects.filter(
        organization=organization, user=user, status=MembershipStatus.ACTIVE
    ).first()


def _with_member_count(queryset: QuerySet[Organization]) -> QuerySet[Organization]:
    return queryset.annotate(
        member_count=Count("memberships", filter=Q(memberships__status=MembershipStatus.ACTIVE))
    )


def list_organizations(query: str = "") -> QuerySet[Organization]:
    """Active organizations, optionally narrowed to names matching ``query``."""
    organizations = Organization.objects.filter(status=OrganizationStatus.ACTIVE)
    query = query.strip()
    if query:
        organizations = organizations.filter(
            Q(name__icontains=query) | Q(name__trigram_similar=query)
        )
    return _with_member_count(organizations)


def list_user_organizations(user: User) -> QuerySet[OrganizationMember]:
    """The user's active memberships with their organizations, for navigation."""
    return (
        OrganizationMember.objects.filter(user=user, status=MembershipStatus.ACTIVE)
        .select_related("organization")
        .order_by("organization__name")
    )


def get_organization(viewer: Viewer, organization_id: UUID) -> Organization:
    """The organization if ``viewer`` may see it, else 404.

    A suspended organization is hidden from everyone except its members and platform staff.
    """
    organization = _with_member_count(Organization.objects.filter(pk=organization_id)).first()
    if organization is None:
        raise Http404
    if organization.status != OrganizationStatus.ACTIVE:
        is_staff = viewer.is_authenticated and is_platform_staff(viewer)
        if not is_staff and get_membership(viewer, organization) is None:
            raise Http404
    return organization


def list_members(
    organization: Organization, viewer_membership: OrganizationMember | None
) -> QuerySet[OrganizationMember]:
    """Active members: all of them for a member, only the public ones for anyone else."""
    members = OrganizationMember.objects.filter(
        organization=organization, status=MembershipStatus.ACTIVE, user__is_active=True
    ).select_related("user__profile")
    if viewer_membership is None:
        members = members.filter(is_public=True)
    return members


def list_pending_invitations(organization: Organization) -> QuerySet[OrganizationInvitation]:
    return OrganizationInvitation.objects.filter(
        organization=organization, status=InvitationStatus.PENDING
    ).select_related("invited_by__profile")
