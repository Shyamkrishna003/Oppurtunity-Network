from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.throttles import ScopedThrottle
from communities import selectors as community_selectors
from communities.policies import actor_for
from opportunities import distribution, policies, selectors
from opportunities.api import serializers
from opportunities.distribution_policies import can_review
from opportunities.models import DistributionStatus, Opportunity, OpportunityCommunity
from users.api.utils import current_user
from users.models import User


def _managed(request: Request, opportunity_id: UUID) -> tuple[User, Opportunity]:
    """The opportunity, for a caller who manages it: 404 if they cannot see it at all, 403 if
    they can see it but not manage it."""
    user = current_user(request)
    opportunity = selectors.get_opportunity(user, opportunity_id)
    membership = selectors.get_membership(user, opportunity.organization_id)
    if not policies.can_manage(user, opportunity, membership):
        raise PermissionDenied()
    return user, opportunity


class OpportunitySharesView(APIView):
    throttle_scope = "opportunity_share"

    def get_throttles(self) -> list[Any]:
        return [ScopedThrottle()] if self.request.method == "POST" else []

    @extend_schema(responses=serializers.ShareSerializer(many=True))
    def get(self, request: Request, opportunity_id: UUID) -> Response:
        """Every community this opportunity was offered to, with each one's decision."""
        _, opportunity = _managed(request, opportunity_id)
        shares = selectors.list_shares(opportunity)
        return Response(serializers.ShareSerializer(shares, many=True).data)

    @extend_schema(
        request=serializers.ShareRequestSerializer,
        responses=serializers.ShareSerializer(many=True),
    )
    def post(self, request: Request, opportunity_id: UUID) -> Response:
        """Share with communities you belong to. Each is shown at once or queued for review,
        according to that community's posting policy. All or nothing."""
        user, opportunity = _managed(request, opportunity_id)
        serializer = serializers.ShareRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        distribution.share(
            actor=user,
            opportunity_id=opportunity.pk,
            community_ids=serializer.validated_data["community_ids"],
        )
        shares = selectors.list_shares(opportunity)
        return Response(serializers.ShareSerializer(shares, many=True).data)


class ShareOptionsView(APIView):
    @extend_schema(responses=serializers.ShareOptionSerializer(many=True))
    def get(self, request: Request, opportunity_id: UUID) -> Response:
        """The caller's communities, each with what sharing into it would do."""
        user, opportunity = _managed(request, opportunity_id)
        options = selectors.share_options(user, opportunity)
        return Response(serializers.ShareOptionSerializer(options, many=True).data)


class OpportunityShareDetailView(APIView):
    @extend_schema(responses={204: None})
    def delete(self, request: Request, opportunity_id: UUID, community_id: UUID) -> Response:
        """Withdraw the opportunity from one community."""
        user, opportunity = _managed(request, opportunity_id)
        distribution.withdraw(actor=user, opportunity_id=opportunity.pk, community_id=community_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CommunityOpportunitiesView(generics.ListAPIView[OpportunityCommunity]):
    """Open opportunities a community shows, newest first. ``?featured=true`` for the pinned
    ones only. Readable by whoever may see the community."""

    serializer_class = serializers.CommunityOpportunitySerializer
    permission_classes = [AllowAny]

    def get_queryset(self) -> QuerySet[OpportunityCommunity]:
        if getattr(self, "swagger_fake_view", False):
            return OpportunityCommunity.objects.none()
        viewer = self.request.user
        community = community_selectors.get_community(viewer, self.kwargs["community_id"])
        featured_only = self.request.query_params.get("featured", "").lower() == "true"
        return selectors.community_opportunities(viewer, community, featured_only=featured_only)

    @extend_schema(parameters=[OpenApiParameter("featured", bool)])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class CommunitySubmissionsView(generics.ListAPIView[OpportunityCommunity]):
    """Shares in one state, for the community's moderators, admins and owners."""

    serializer_class = serializers.SubmissionSerializer

    def get_queryset(self) -> QuerySet[OpportunityCommunity]:
        if getattr(self, "swagger_fake_view", False):
            return OpportunityCommunity.objects.none()
        user = current_user(self.request)
        community = community_selectors.get_community(user, self.kwargs["community_id"])
        membership = community_selectors.get_membership(user, community)
        if not can_review(actor_for(user.pk, membership)):
            self.permission_denied(self.request)
        requested = self.request.query_params.get("status", DistributionStatus.PENDING)
        if requested not in DistributionStatus.values:
            raise ValidationError(
                {"status": [f"Choose one of: {', '.join(DistributionStatus.values)}."]}
            )
        return selectors.community_queue(community, DistributionStatus(requested))

    @extend_schema(parameters=[OpenApiParameter("status", str, enum=DistributionStatus.values)])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


_DECISIONS = {
    "approve": DistributionStatus.APPROVED,
    "reject": DistributionStatus.REJECTED,
    "remove": DistributionStatus.REMOVED,
}
_FEATURING = {"feature": True, "unfeature": False}
SUBMISSION_ACTIONS = (*_DECISIONS, *_FEATURING)


class SubmissionActionView(APIView):
    """One explicit endpoint per decision a community makes about a share."""

    @extend_schema(
        request=serializers.RejectSerializer,
        responses=serializers.SubmissionSerializer,
        parameters=[OpenApiParameter("action", str, "path", enum=list(SUBMISSION_ACTIONS))],
    )
    def post(self, request: Request, community_id: str, share_id: str, action: str) -> Response:
        # This route is matched by a regular expression, so the IDs arrive as text.
        user = current_user(request)
        community = community_selectors.get_community(user, UUID(community_id))
        if action in _FEATURING:
            share = distribution.set_featured(
                actor=user,
                community_id=community.pk,
                share_id=UUID(share_id),
                featured=_FEATURING[action],
            )
        else:
            serializer = serializers.RejectSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            share = distribution.review(
                actor=user,
                community_id=community.pk,
                share_id=UUID(share_id),
                decision=_DECISIONS[action],
                reason=serializer.validated_data["reason"],
            )
        return Response(serializers.SubmissionSerializer(share).data)
