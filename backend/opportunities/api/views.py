from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from common.throttles import ScopedThrottle
from opportunities import policies, selectors, services
from opportunities.api import serializers
from opportunities.api.feed_views import feed_response
from opportunities.models import CloseReason, Opportunity, OpportunityStatus, OpportunityType
from users.api.utils import current_user
from users.permissions import IsVerified


def _detail(request: Request, opportunity_id: UUID, status_code: int = 200) -> Response:
    """The opportunity as the caller now sees it, including what they may do with it."""
    opportunity = selectors.get_opportunity(request.user, opportunity_id)
    can_manage = request.user.is_authenticated and policies.can_manage(
        request.user,
        opportunity,
        selectors.get_membership(request.user, opportunity.organization_id),
    )
    context = {
        "can_manage": can_manage,
        "communities": selectors.communities_showing(request.user, opportunity),
        "is_saved": selectors.is_saved(request.user, opportunity),
    }
    data = serializers.OpportunityDetailSerializer(opportunity, context=context).data
    return Response(data, status=status_code)


class OpportunityListView(APIView):
    """``GET`` is the public feed; ``POST`` creates a draft."""

    def get_permissions(self) -> list[BasePermission]:
        return [IsVerified()] if self.request.method == "POST" else [AllowAny()]

    def get_throttles(self) -> list[BaseThrottle]:
        throttle = ScopedThrottle()
        # ScopedThrottle reads the scope from the view, and the two methods have their own.
        self.throttle_scope = (
            "opportunity_create" if self.request.method == "POST" else "opportunity_search"
        )
        return [throttle]

    @extend_schema(
        parameters=[serializers.FeedQuerySerializer],
        responses=serializers.FeedItemSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Search and browse open opportunities the caller may see.

        Signed-in callers also get, for each result, whether they saved it and why it fits
        them. Ordering by ``newest`` pages with a cursor; other orders page by offset and
        stop at 500 results.
        """
        return feed_response(request, self)

    @extend_schema(
        request=serializers.OpportunityCreateSerializer,
        responses={201: serializers.OpportunityDetailSerializer},
    )
    def post(self, request: Request) -> Response:
        """Create a draft. Give ``organization_id`` to post on behalf of an organization
        where you are an owner, admin or recruiter; omit it for a personal opportunity."""
        serializer = serializers.OpportunityCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        opportunity = services.create_opportunity(
            creator=current_user(request),
            type=OpportunityType(data.pop("type")),
            organization_id=data.pop("organization_id", None),
            skill_ids=data.pop("skill_ids", ()),
            job=data.pop("job", None),
            **data,
        )
        return _detail(request, opportunity.pk, status.HTTP_201_CREATED)


class OpportunityDetailView(APIView):
    def get_permissions(self) -> list[BasePermission]:
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    @extend_schema(responses=serializers.OpportunityDetailSerializer)
    def get(self, request: Request, opportunity_id: UUID) -> Response:
        return _detail(request, opportunity_id)

    @extend_schema(
        request=serializers.OpportunityFieldsSerializer,
        responses=serializers.OpportunityDetailSerializer,
    )
    def patch(self, request: Request, opportunity_id: UUID) -> Response:
        """Edit. Everything is editable in a draft; once published, only the description,
        the deadline and the number of openings."""
        opportunity = selectors.get_opportunity(request.user, opportunity_id)
        serializer = serializers.OpportunityFieldsSerializer(
            opportunity, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        services.update_opportunity(
            actor=current_user(request),
            opportunity_id=opportunity.pk,
            job_changes=data.pop("job", None),
            skill_ids=data.pop("skill_ids", None),
            changes=data,
        )
        return _detail(request, opportunity_id)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, opportunity_id: UUID) -> Response:
        """Delete a draft. Anything that was published is closed and archived instead."""
        selectors.get_opportunity(request.user, opportunity_id)
        services.delete_draft(actor=current_user(request), opportunity_id=opportunity_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublishView(APIView):
    @extend_schema(request=None, responses=serializers.OpportunityDetailSerializer)
    def post(self, request: Request, opportunity_id: UUID) -> Response:
        """Publish a draft. Answers 422 with a message per field if anything is missing."""
        selectors.get_opportunity(request.user, opportunity_id)
        services.publish(actor=current_user(request), opportunity_id=opportunity_id)
        return _detail(request, opportunity_id)


class CloseView(APIView):
    @extend_schema(
        request=serializers.CloseSerializer, responses=serializers.OpportunityDetailSerializer
    )
    def post(self, request: Request, opportunity_id: UUID) -> Response:
        """Stop taking applications. The opportunity stays visible, marked as closed."""
        selectors.get_opportunity(request.user, opportunity_id)
        serializer = serializers.CloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.close(
            actor=current_user(request),
            opportunity_id=opportunity_id,
            reason=CloseReason(serializer.validated_data["reason"]),
        )
        return _detail(request, opportunity_id)


class ArchiveView(APIView):
    @extend_schema(request=None, responses=serializers.OpportunityDetailSerializer)
    def post(self, request: Request, opportunity_id: UUID) -> Response:
        """Take a closed or expired opportunity out of every public view."""
        selectors.get_opportunity(request.user, opportunity_id)
        services.archive(actor=current_user(request), opportunity_id=opportunity_id)
        return _detail(request, opportunity_id)


class MyOpportunitiesView(generics.ListAPIView[Opportunity]):
    """Opportunities the caller manages, in every state including drafts and archived."""

    serializer_class = serializers.OpportunitySerializer

    def get_queryset(self) -> QuerySet[Opportunity]:
        if getattr(self, "swagger_fake_view", False):
            return Opportunity.objects.none()
        requested = self.request.query_params.get("status", "")
        if requested and requested not in OpportunityStatus.values:
            raise ValidationError(
                {"status": [f"Choose one of: {', '.join(OpportunityStatus.values)}."]}
            )
        return selectors.list_managed(current_user(self.request), requested)

    @extend_schema(parameters=[OpenApiParameter("status", str, enum=OpportunityStatus.values)])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)
