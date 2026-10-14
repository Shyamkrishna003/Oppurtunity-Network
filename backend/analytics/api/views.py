from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics import selectors
from analytics.api import serializers
from audit.api.views import IsPlatformAdmin


class PlatformTotalsView(APIView):
    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses=serializers.PlatformTotalsSerializer)
    def get(self, request: Request) -> Response:
        """Counts across the platform, for its admins. Up to a minute old."""
        return Response(serializers.PlatformTotalsSerializer(selectors.platform_totals()).data)
