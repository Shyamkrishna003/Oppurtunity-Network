from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.pagination import CursorPagination
from common.throttles import ScopedThrottle
from moderation import policies, selectors, services
from moderation.api import serializers
from moderation.models import ActionType, Report, ReportCategory, ReportStatus, TargetType
from users.api.utils import current_user
from users.models import User
from users.permissions import IsVerified


class IsModerator(BasePermission):
    """A platform moderator or admin. Nothing an organization or a community grants counts."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return isinstance(user, User) and policies.can_moderate(user)


class FileReportView(APIView):
    permission_classes = [IsVerified]
    throttle_classes = [ScopedThrottle]
    throttle_scope = "report_create"

    @extend_schema(
        request=serializers.FileReportSerializer, responses={201: serializers.MyReportSerializer}
    )
    def post(self, request: Request) -> Response:
        """Report a person, organization, community or opportunity to the moderators.

        Answers 404 for something the caller cannot see, 422 ``own_content`` for themselves
        or something they manage, and 409 ``already_reported`` while an earlier report of
        theirs about the same thing is still being looked at.

        With ``community_id`` the report goes to that community's moderators instead, who
        can take the opportunity out of their community. 422 ``not_a_member`` or
        ``not_in_community`` when it cannot.
        """
        serializer = serializers.FileReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        report = services.file_report(
            reporter=current_user(request),
            target_type=TargetType(data["target_type"]),
            target_id=data["target_id"],
            category=ReportCategory(data["category"]),
            description=data["description"],
            community_id=data["community_id"],
        )
        return Response(serializers.MyReportSerializer(report).data, status=status.HTTP_201_CREATED)


class MyReportsView(generics.ListAPIView[Report]):
    """The caller's own reports, newest first."""

    serializer_class = serializers.MyReportSerializer

    def get_queryset(self) -> QuerySet[Report]:
        if getattr(self, "swagger_fake_view", False):
            return Report.objects.none()
        return selectors.list_mine(current_user(self.request))


def _choice(request: Request, name: str, allowed: list[str]) -> str:
    value = request.query_params.get(name, "")
    if value and value not in allowed:
        raise ValidationError({name: [f"Choose one of: {', '.join(allowed)}."]})
    return value


class _OldestFirst(CursorPagination):
    """The longest-waiting report first."""

    ordering = ("created_at", "id")


class ReportQueueView(generics.ListAPIView[Report]):
    """Reports for the platform's moderators, the longest-waiting first."""

    permission_classes = [IsModerator]
    serializer_class = serializers.ReportSerializer
    pagination_class = _OldestFirst

    def get_queryset(self) -> QuerySet[Report]:
        if getattr(self, "swagger_fake_view", False):
            return Report.objects.none()
        return selectors.queue(
            _choice(self.request, "status", ReportStatus.values),
            _choice(self.request, "target_type", TargetType.values),
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, enum=ReportStatus.values),
            OpenApiParameter("target_type", str, enum=TargetType.values),
        ]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


def _detail(request: Request, report: Report) -> Response:
    context = {"viewer": current_user(request)}
    return Response(serializers.ReportDetailSerializer(report, context=context).data)


class ReportDetailView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(responses=serializers.ReportDetailSerializer)
    def get(self, request: Request, report_id: UUID) -> Response:
        return _detail(request, selectors.get_report(report_id))


class TargetDetailView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(responses=serializers.TargetDetailSerializer)
    def get(self, request: Request, target_type: str, target_id: UUID) -> Response:
        """Anything that can be moderated, with how it stands, what has been done to it,
        and what the caller could do now. Nothing is hidden from a moderator here: a
        suspended account or a removed opportunity can still be opened."""
        if target_type not in TargetType.values:
            raise NotFound()
        target = selectors.load_target(TargetType(target_type), target_id)
        possible = policies.open_to(current_user(request), target)
        return Response(
            serializers.TargetDetailSerializer(
                {
                    "target": selectors.describe(target),
                    "standing": selectors.standing(target),
                    "possible_actions": sorted(possible),
                    "timed_actions": sorted(possible & policies.TIMED),
                    "actions": selectors.actions_about(target_type, target_id)[:50],
                }
            ).data
        )


class ClaimView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(request=None, responses=serializers.ReportDetailSerializer)
    def post(self, request: Request, report_id: UUID) -> Response:
        """Take the report on: it moves to "under review" with the caller's name on it."""
        return _detail(request, services.claim(actor=current_user(request), report_id=report_id))


class DismissView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(
        request=serializers.DismissSerializer, responses=serializers.ReportDetailSerializer
    )
    def post(self, request: Request, report_id: UUID) -> Response:
        """Decide that the report needs no action. The note is for other moderators only."""
        serializer = serializers.DismissSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _detail(
            request,
            services.dismiss(
                actor=current_user(request),
                report_id=report_id,
                note=serializer.validated_data["note"],
            ),
        )


class ResolveView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(
        request=serializers.ResolveSerializer, responses=serializers.ReportDetailSerializer
    )
    def post(self, request: Request, report_id: UUID) -> Response:
        """Act on what was reported, which settles this report and any others still waiting
        about the same thing. The reason is shown to the owners of what is acted on."""
        serializer = serializers.ResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = selectors.get_report(report_id)
        services.act(
            actor=current_user(request),
            target_type=TargetType(report.target_type),
            target_id=report.target_id,
            action=ActionType(serializer.validated_data["action"]),
            reason=serializer.validated_data["reason"],
            until=serializer.validated_data["until"],
            report_id=report.pk,
        )
        return _detail(request, selectors.get_report(report_id))


# --- A community's own reports ----------------------------------------------------------
#
# Open to the community's moderators, admins and owners; the services check that on every
# call. Platform staff have no standing here, and these people have none in the platform's
# queue.


def _community_detail(request: Request, report: Report) -> Response:
    context = {"viewer": current_user(request)}
    return Response(serializers.CommunityReportDetailSerializer(report, context=context).data)


class CommunityReportQueueView(generics.ListAPIView[Report]):
    """Reports sent to one community's moderators, the longest-waiting first."""

    serializer_class = serializers.CommunityReportSerializer
    pagination_class = _OldestFirst

    def get_queryset(self) -> QuerySet[Report]:
        if getattr(self, "swagger_fake_view", False):
            return Report.objects.none()
        community = services.require_community_moderator(
            current_user(self.request), self.kwargs["community_id"]
        )
        return selectors.queue(
            _choice(self.request, "status", ReportStatus.values), community_id=community.pk
        )

    @extend_schema(parameters=[OpenApiParameter("status", str, enum=ReportStatus.values)])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class CommunityReportDetailView(APIView):
    @extend_schema(responses=serializers.CommunityReportDetailSerializer)
    def get(self, request: Request, community_id: UUID, report_id: UUID) -> Response:
        community = services.require_community_moderator(current_user(request), community_id)
        return _community_detail(
            request, selectors.get_report(report_id, community_id=community.pk)
        )


class CommunityClaimView(APIView):
    @extend_schema(request=None, responses=serializers.CommunityReportDetailSerializer)
    def post(self, request: Request, community_id: UUID, report_id: UUID) -> Response:
        """Take the report on. 403 for a report about something the caller manages."""
        return _community_detail(
            request,
            services.claim(
                actor=current_user(request), report_id=report_id, community_id=community_id
            ),
        )


class CommunityDismissView(APIView):
    @extend_schema(
        request=serializers.DismissSerializer,
        responses=serializers.CommunityReportDetailSerializer,
    )
    def post(self, request: Request, community_id: UUID, report_id: UUID) -> Response:
        """Decide that the report needs no action. The note is for the other moderators."""
        serializer = serializers.DismissSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _community_detail(
            request,
            services.dismiss(
                actor=current_user(request),
                report_id=report_id,
                note=serializer.validated_data["note"],
                community_id=community_id,
            ),
        )


class CommunityRemoveView(APIView):
    @extend_schema(
        request=serializers.RemoveSerializer,
        responses=serializers.CommunityReportDetailSerializer,
    )
    def post(self, request: Request, community_id: UUID, report_id: UUID) -> Response:
        """Take what was reported out of this community, which settles this report and any
        others about it waiting here. It stays wherever else it is shown. 409
        ``action_not_possible`` when the community no longer shows it."""
        serializer = serializers.RemoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _community_detail(
            request,
            services.remove_from_community(
                actor=current_user(request),
                community_id=community_id,
                report_id=report_id,
                reason=serializer.validated_data["reason"],
            ),
        )


class CommunityEscalateView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, community_id: UUID, report_id: UUID) -> Response:
        """Pass the report up to the platform's moderators. It leaves this community's
        queue for good."""
        services.escalate(
            actor=current_user(request), community_id=community_id, report_id=report_id
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class ActView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(request=serializers.ActSerializer, responses={201: serializers.ActionSerializer})
    def post(self, request: Request) -> Response:
        """Act on something without a report: hide or remove it, or restore something hidden."""
        serializer = serializers.ActSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        taken = services.act(
            actor=current_user(request),
            target_type=TargetType(data["target_type"]),
            target_id=data["target_id"],
            action=ActionType(data["action"]),
            reason=data["reason"],
            until=data["until"],
        )
        return Response(serializers.ActionSerializer(taken).data, status=status.HTTP_201_CREATED)
