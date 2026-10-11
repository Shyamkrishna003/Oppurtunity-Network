from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from common.throttles import ScopedThrottle
from communities import policies, selectors, services
from communities.api import serializers
from communities.models import Community, CommunityMember, CommunityRole, MemberStatus
from users.api.utils import current_user
from users.permissions import IsVerified
from users.policies import is_platform_staff


def _validated(serializer_class: type[BaseSerializer[Any]], request: Request) -> dict[str, Any]:
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    data: dict[str, Any] = serializer.validated_data
    return data


def _detail(request: Request, community_id: UUID, status_code: int = 200) -> Response:
    """The community as the caller now sees it, including what they may do."""
    community = selectors.get_community(request.user, community_id)
    membership = selectors.get_membership(request.user, community)
    data = serializers.CommunityDetailSerializer(community, context={"membership": membership}).data
    return Response(data, status=status_code)


class CommunityListView(generics.ListAPIView[Community]):
    """Browse communities (public ones, plus private ones you belong to), or create one."""

    serializer_class = serializers.CommunitySerializer
    throttle_scope = "community_create"

    def get_permissions(self) -> list[BasePermission]:
        return [IsVerified()] if self.request.method == "POST" else [AllowAny()]

    def get_throttles(self) -> list[BaseThrottle]:
        return [ScopedThrottle()] if self.request.method == "POST" else []

    def get_queryset(self) -> QuerySet[Community]:
        params = self.request.query_params
        return selectors.list_communities(
            self.request.user, params.get("q", "")[:120], params.get("category", "")[:60]
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Match on name."),
            OpenApiParameter("category", str, description="Exact category."),
        ]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=serializers.CommunityWriteSerializer,
        responses={201: serializers.CommunityDetailSerializer},
    )
    def post(self, request: Request) -> Response:
        """Create a community. The caller becomes its owner."""
        community = services.create_community(
            creator=current_user(request),
            **_validated(serializers.CommunityWriteSerializer, request),
        )
        return _detail(request, community.pk, status.HTTP_201_CREATED)


class MyCommunitiesView(generics.ListAPIView[CommunityMember]):
    """The caller's communities, invitations and pending requests."""

    serializer_class = serializers.MyCommunitySerializer
    pagination_class = None  # bounded by how many communities one person joins

    def get_queryset(self) -> QuerySet[CommunityMember]:
        if getattr(self, "swagger_fake_view", False):
            return CommunityMember.objects.none()
        return selectors.list_user_communities(current_user(self.request))


class CommunityDetailView(APIView):
    def get_permissions(self) -> list[BasePermission]:
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    @extend_schema(responses=serializers.CommunityDetailSerializer)
    def get(self, request: Request, community_id: UUID) -> Response:
        return _detail(request, community_id)

    @extend_schema(
        request=serializers.CommunityWriteSerializer,
        responses=serializers.CommunityDetailSerializer,
    )
    def patch(self, request: Request, community_id: UUID) -> Response:
        """Edit the community's details and policies. Owners and admins only."""
        community = selectors.get_community(request.user, community_id)
        serializer = serializers.CommunityWriteSerializer(
            community, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        services.update_community(
            actor=current_user(request),
            community_id=community.pk,
            changes=serializer.validated_data,
        )
        return _detail(request, community_id)


class RulesView(APIView):
    @extend_schema(
        request=serializers.RulesSerializer, responses=serializers.CommunityDetailSerializer
    )
    def put(self, request: Request, community_id: UUID) -> Response:
        """Replace the community's rules with the given ordered list."""
        selectors.get_community(request.user, community_id)
        services.replace_rules(
            actor=current_user(request),
            community_id=community_id,
            **_validated(serializers.RulesSerializer, request),
        )
        return _detail(request, community_id)


class JoinView(APIView):
    permission_classes = [IsVerified]
    throttle_classes = [ScopedThrottle]
    throttle_scope = "community_join"

    @extend_schema(request=None, responses=serializers.CommunityDetailSerializer)
    def post(self, request: Request, community_id: UUID) -> Response:
        """Join, ask to join, or accept an invitation, depending on the community's join
        policy and the caller's current state. Repeating it changes nothing."""
        services.join(user=current_user(request), community_id=community_id)
        return _detail(request, community_id)


class LeaveView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, community_id: UUID) -> Response:
        """Leave, decline an invitation, or withdraw a request to join."""
        services.leave(user=current_user(request), community_id=community_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# Which membership states can be listed, and what the caller needs in order to list them.
_LISTABLE: dict[MemberStatus, Callable[[policies.Actor], bool]] = {
    MemberStatus.ACTIVE: policies.is_member,
    MemberStatus.PENDING: policies.can_review_requests,
    MemberStatus.INVITED: policies.can_manage,
    MemberStatus.BANNED: policies.can_manage,
}


class MemberListView(generics.ListAPIView[CommunityMember]):
    """People in the community by state. Members see active members; moderators also see
    requests to join; admins also see invited and banned people."""

    serializer_class = serializers.CommunityMemberSerializer

    def get_queryset(self) -> QuerySet[CommunityMember]:
        if getattr(self, "swagger_fake_view", False):
            return CommunityMember.objects.none()
        user = current_user(self.request)
        community = selectors.get_community(user, self.kwargs["community_id"])
        requested = self.request.query_params.get("status", MemberStatus.ACTIVE)
        if requested not in _LISTABLE:
            raise ValidationError({"status": [f"Choose one of: {', '.join(_LISTABLE)}."]})
        member_status = MemberStatus(requested)
        actor = policies.actor_for(user.pk, selectors.get_membership(user, community))
        if not _LISTABLE[member_status](actor) and not is_platform_staff(user):
            self.permission_denied(self.request)
        return selectors.list_members(community, member_status)

    @extend_schema(parameters=[OpenApiParameter("status", str, enum=[s.value for s in _LISTABLE])])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class MemberDetailView(APIView):
    @extend_schema(
        request=serializers.RoleSerializer, responses=serializers.CommunityMemberSerializer
    )
    def patch(self, request: Request, community_id: UUID, member_id: UUID) -> Response:
        """Change a member's role."""
        selectors.get_community(request.user, community_id)
        member = services.change_role(
            actor=current_user(request),
            community_id=community_id,
            member_id=member_id,
            role=CommunityRole(_validated(serializers.RoleSerializer, request)["role"]),
        )
        return Response(serializers.CommunityMemberSerializer(member).data)


_MEMBER_ACTIONS = {
    "approve": services.approve,
    "reject": services.reject,
    "remove": services.remove,
    "ban": services.ban,
    "unban": services.unban,
}


class MemberActionView(APIView):
    """One explicit endpoint per membership transition made by a moderator or admin."""

    @extend_schema(
        request=None,
        responses=serializers.CommunityMemberSerializer,
        parameters=[OpenApiParameter("action", str, "path", enum=list(_MEMBER_ACTIONS))],
    )
    def post(self, request: Request, community_id: str, member_id: str, action: str) -> Response:
        # This route is matched by a regular expression, so the IDs arrive as text.
        community = selectors.get_community(request.user, UUID(community_id))
        member = _MEMBER_ACTIONS[action](
            actor=current_user(request), community_id=community.pk, member_id=UUID(member_id)
        )
        return Response(serializers.CommunityMemberSerializer(member).data)


class InvitationView(APIView):
    throttle_classes = [ScopedThrottle]
    throttle_scope = "community_invite"

    @extend_schema(
        request=serializers.InviteSerializer, responses={201: serializers.CommunityMemberSerializer}
    )
    def post(self, request: Request, community_id: UUID) -> Response:
        """Invite a user whose profile you can open. Owners and admins only."""
        selectors.get_community(request.user, community_id)
        member = services.invite(
            actor=current_user(request),
            community_id=community_id,
            **_validated(serializers.InviteSerializer, request),
        )
        return Response(
            serializers.CommunityMemberSerializer(member).data, status=status.HTTP_201_CREATED
        )
