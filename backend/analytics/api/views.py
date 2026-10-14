from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics import policies, selectors
from analytics.api import serializers
from audit.api.views import IsPlatformAdmin
from opportunities import selectors as opportunities
from opportunities.policies import can_manage
from users.api.utils import current_user

DAYS_SHOWN = 14


class PlatformTotalsView(APIView):
    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses=serializers.PlatformTotalsSerializer)
    def get(self, request: Request) -> Response:
        """Counts across the platform, for its admins. Up to a minute old."""
        return Response(serializers.PlatformTotalsSerializer(selectors.platform_totals()).data)


class OpportunityNumbersView(APIView):
    @extend_schema(responses=serializers.OpportunityNumbersSerializer)
    def get(self, request: Request, opportunity_id: UUID) -> Response:
        """How an opportunity is doing, counted now. For the people who manage it: 404 if
        the caller cannot see it, 403 if they can but do not manage it."""
        user = current_user(request)
        opportunity = opportunities.get_opportunity(user, opportunity_id)
        membership = opportunities.get_membership(user, opportunity.organization_id)
        if not can_manage(user, opportunity, membership):
            raise PermissionDenied()
        numbers = selectors.numbers_for([opportunity.pk])[opportunity.pk]
        data = {
            **numbers,
            "popularity_score": policies.popularity(
                **{name: value for name, value in numbers.items() if name != "views"}
            ),
            "views_by_day": [
                {"date": day, "views": views}
                for day, views in selectors.views_by_day(opportunity.pk, DAYS_SHOWN)
            ],
        }
        return Response(serializers.OpportunityNumbersSerializer(data).data)
