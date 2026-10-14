from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from audit import selectors as audit
from audit.api.serializers import AuditLogSerializer
from audit.models import AuditLog
from common.throttles import ScopedThrottle
from organizations import selectors, services
from organizations.api import serializers
from organizations.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    OrganizationRole,
)
from organizations.policies import can_manage, can_read_audit
from users.api.utils import current_user
from users.permissions import IsVerified


def _validated(serializer_class: type[BaseSerializer[Any]], request: Request) -> dict[str, Any]:
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    data: dict[str, Any] = serializer.validated_data
    return data


def _detail(request: Request, organization_id: UUID, status_code: int = 200) -> Response:
    """The organization as the caller now sees it, including what they may do."""
    organization = selectors.get_organization(request.user, organization_id)
    membership = selectors.get_membership(request.user, organization)
    data = serializers.OrganizationDetailSerializer(
        organization, context={"membership": membership}
    ).data
    return Response(data, status=status_code)


class OrganizationListView(generics.ListAPIView[Organization]):
    """Browse organizations (public), or create one (verified users)."""

    serializer_class = serializers.OrganizationSerializer
    throttle_scope = "organization_create"

    def get_permissions(self) -> list[BasePermission]:
        return [IsVerified()] if self.request.method == "POST" else [AllowAny()]

    def get_throttles(self) -> list[BaseThrottle]:
        return [ScopedThrottle()] if self.request.method == "POST" else []

    def get_queryset(self) -> QuerySet[Organization]:
        return selectors.list_organizations(self.request.query_params.get("q", "")[:120])

    @extend_schema(parameters=[OpenApiParameter("q", str, description="Match on name.")])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=serializers.OrganizationWriteSerializer,
        responses={201: serializers.OrganizationDetailSerializer},
    )
    def post(self, request: Request) -> Response:
        """Create an organization. The caller becomes its owner."""
        organization = services.create_organization(
            creator=current_user(request),
            **_validated(serializers.OrganizationWriteSerializer, request),
        )
        return _detail(request, organization.pk, status.HTTP_201_CREATED)


class MyOrganizationsView(generics.ListAPIView[OrganizationMember]):
    """The caller's own organizations and roles."""

    serializer_class = serializers.MyOrganizationSerializer
    pagination_class = None  # a person belongs to a handful of organizations

    def get_queryset(self) -> QuerySet[OrganizationMember]:
        if getattr(self, "swagger_fake_view", False):
            return OrganizationMember.objects.none()
        return selectors.list_user_organizations(current_user(self.request))


class OrganizationDetailView(APIView):
    def get_permissions(self) -> list[BasePermission]:
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    @extend_schema(responses=serializers.OrganizationDetailSerializer)
    def get(self, request: Request, organization_id: UUID) -> Response:
        return _detail(request, organization_id)

    @extend_schema(
        request=serializers.OrganizationWriteSerializer,
        responses=serializers.OrganizationDetailSerializer,
    )
    def patch(self, request: Request, organization_id: UUID) -> Response:
        """Edit the organization's details. Owners and admins only."""
        organization = selectors.get_organization(request.user, organization_id)
        serializer = serializers.OrganizationWriteSerializer(
            organization, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        services.update_organization(
            actor=current_user(request),
            organization_id=organization.pk,
            changes=serializer.validated_data,
        )
        return _detail(request, organization_id)


class MemberListView(generics.ListAPIView[OrganizationMember]):
    """Active members. Members see everyone; others see only public memberships."""

    serializer_class = serializers.MemberSerializer
    permission_classes = [AllowAny]

    def get_queryset(self) -> QuerySet[OrganizationMember]:
        if getattr(self, "swagger_fake_view", False):
            return OrganizationMember.objects.none()
        organization = selectors.get_organization(self.request.user, self.kwargs["organization_id"])
        membership = selectors.get_membership(self.request.user, organization)
        return selectors.list_members(organization, membership)


class MemberDetailView(APIView):
    @extend_schema(
        request=serializers.MemberUpdateSerializer, responses=serializers.MemberSerializer
    )
    def patch(self, request: Request, organization_id: UUID, member_id: UUID) -> Response:
        """Change a member's role, or your own membership's visibility to outsiders."""
        selectors.get_organization(request.user, organization_id)
        user = current_user(request)
        data = _validated(serializers.MemberUpdateSerializer, request)
        if "role" in data:
            member = services.change_role(
                actor=user,
                organization_id=organization_id,
                member_id=member_id,
                role=OrganizationRole(data["role"]),
            )
        else:
            member = services.set_membership_visibility(
                user=user,
                organization_id=organization_id,
                member_id=member_id,
                is_public=data["is_public"],
            )
        return Response(serializers.MemberSerializer(member).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, organization_id: UUID, member_id: UUID) -> Response:
        """Remove a member. To remove yourself, use leave."""
        selectors.get_organization(request.user, organization_id)
        services.remove_member(
            actor=current_user(request), organization_id=organization_id, member_id=member_id
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class LeaveView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, organization_id: UUID) -> Response:
        """Leave the organization. The last owner cannot leave."""
        services.leave(user=current_user(request), organization_id=organization_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TransferOwnershipView(APIView):
    @extend_schema(
        request=serializers.TransferOwnershipSerializer,
        responses=serializers.OrganizationDetailSerializer,
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        """Make another member an owner; the caller becomes an admin."""
        selectors.get_organization(request.user, organization_id)
        services.transfer_ownership(
            actor=current_user(request),
            organization_id=organization_id,
            **_validated(serializers.TransferOwnershipSerializer, request),
        )
        return _detail(request, organization_id)


class InvitationListView(generics.ListAPIView[OrganizationInvitation]):
    """Open invitations (owners and admins), and sending a new one."""

    serializer_class = serializers.InvitationSerializer
    throttle_scope = "organization_invite"

    def get_throttles(self) -> list[BaseThrottle]:
        return [ScopedThrottle()] if self.request.method == "POST" else []

    def get_queryset(self) -> QuerySet[OrganizationInvitation]:
        if getattr(self, "swagger_fake_view", False):
            return OrganizationInvitation.objects.none()
        organization = selectors.get_organization(self.request.user, self.kwargs["organization_id"])
        if not can_manage(selectors.get_membership(self.request.user, organization)):
            self.permission_denied(self.request)
        return selectors.list_pending_invitations(organization)

    @extend_schema(
        request=serializers.InvitationCreateSerializer,
        responses={201: serializers.InvitationSerializer},
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        """Invite an email address. Admins may invite recruiters and members only."""
        selectors.get_organization(request.user, organization_id)
        data = _validated(serializers.InvitationCreateSerializer, request)
        invitation = services.invite(
            actor=current_user(request),
            organization_id=organization_id,
            email=data["email"],
            role=OrganizationRole(data["role"]),
        )
        return Response(
            serializers.InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED
        )


class InvitationDetailView(APIView):
    @extend_schema(responses={204: None})
    def delete(self, request: Request, organization_id: UUID, invitation_id: UUID) -> Response:
        """Withdraw an open invitation."""
        selectors.get_organization(request.user, organization_id)
        services.revoke_invitation(
            actor=current_user(request),
            organization_id=organization_id,
            invitation_id=invitation_id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReceivedInvitationView(APIView):
    @extend_schema(responses=serializers.ReceivedInvitationSerializer)
    def get(self, request: Request, token: str) -> Response:
        """The invitation behind an emailed link, for the person it was sent to."""
        invitation = services.get_invitation(user=current_user(request), token=token)
        return Response(serializers.ReceivedInvitationSerializer(invitation).data)


class AcceptInvitationView(APIView):
    permission_classes = [IsVerified]

    @extend_schema(request=None, responses=serializers.MyOrganizationSerializer)
    def post(self, request: Request, token: str) -> Response:
        """Join the organization with the invited role. Works once."""
        membership = services.accept_invitation(user=current_user(request), token=token)
        return Response(serializers.MyOrganizationSerializer(membership).data)


class DeclineInvitationView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, token: str) -> Response:
        services.decline_invitation(user=current_user(request), token=token)
        return Response(status=status.HTTP_204_NO_CONTENT)


# What an organization's owners are shown of the records filed under it: its membership,
# its opportunities, and what was done with the applications and registrations it received.
# Not referrals, where who asked whom stays between those two until a referral is made, and
# not which moderator acted on it.
AUDIT_KINDS = ("organization.", "opportunity.", "application.", "event.")


class AuditLogView(generics.ListAPIView[AuditLog]):
    """What has been done in the organization, newest first. For its owners."""

    serializer_class = AuditLogSerializer

    def get_queryset(self) -> QuerySet[AuditLog]:
        if getattr(self, "swagger_fake_view", False):
            return AuditLog.objects.none()
        user = current_user(self.request)
        organization = selectors.get_organization(user, self.kwargs["organization_id"])
        if not can_read_audit(selectors.get_membership(user, organization)):
            raise PermissionDenied()
        return audit.search(organization_id=organization.pk, kinds=AUDIT_KINDS)
