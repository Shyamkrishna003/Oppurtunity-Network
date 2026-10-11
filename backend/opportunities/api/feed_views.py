from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.pagination import CursorPagination, RankedPagination
from opportunities import feed, relevance, selectors, services
from opportunities.api import serializers
from opportunities.models import SavedOpportunity
from users.api.utils import current_user
from users.models import User


class NewestFirstPagination(CursorPagination):
    ordering = ("-published_at", "-id")


def feed_response(request: Request, view: APIView) -> Response:
    """Search and browse open opportunities. See ``FeedQuerySerializer`` for the parameters."""
    params = request.query_params
    # ``skill`` may be repeated; everything else is taken once.
    serializer = serializers.FeedQuerySerializer(
        data={**params.dict(), **({"skill": params.getlist("skill")} if "skill" in params else {})}
    )
    serializer.is_valid(raise_exception=True)
    query = feed.FeedQuery(**serializer.validated_data)

    viewer = request.user
    matcher = relevance.load_matcher(viewer) if isinstance(viewer, User) else None
    opportunities = feed.build_feed(viewer, query, matcher)

    # Newest-first can use a cursor; a computed order has to page by offset.
    paginator = (
        NewestFirstPagination() if query.effective_sort == feed.NEWEST else RankedPagination()
    )
    page = paginator.paginate_queryset(opportunities, request, view=view) or []

    matches = {}
    if matcher is not None:
        names = relevance.community_names_by_opportunity(matcher, [o.pk for o in page])
        matches = {o.pk: relevance.explain(matcher, o, names.get(o.pk, [])) for o in page}
    data = serializers.FeedItemSerializer(page, many=True, context={"matches": matches}).data
    return paginator.get_paginated_response(data)


class SaveView(APIView):
    @extend_schema(request=None, responses={204: None})
    def put(self, request: Request, opportunity_id: UUID) -> Response:
        """Save an opportunity for later. Saving twice changes nothing."""
        services.save_for_later(user=current_user(request), opportunity_id=opportunity_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, opportunity_id: UUID) -> Response:
        services.unsave(user=current_user(request), opportunity_id=opportunity_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SavedOpportunitiesView(generics.ListAPIView[SavedOpportunity]):
    """What the caller saved, most recently saved first, including closed ones."""

    serializer_class = serializers.SavedOpportunitySerializer

    def get_queryset(self) -> QuerySet[SavedOpportunity]:
        if getattr(self, "swagger_fake_view", False):
            return SavedOpportunity.objects.none()
        return selectors.list_saved(current_user(self.request))
