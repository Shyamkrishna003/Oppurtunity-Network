from typing import Any

from django.conf import settings
from django.urls import path
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.throttles import ScopedThrottle
from realtime import tickets
from users.api.utils import current_user


class TicketSerializer(serializers.Serializer[Any]):
    ticket = serializers.CharField()
    expires_in = serializers.IntegerField(help_text="Seconds.")


class SocketTicketView(APIView):
    throttle_classes = [ScopedThrottle]
    throttle_scope = "ws_ticket"

    @extend_schema(request=None, responses=TicketSerializer)
    def post(self, request: Request) -> Response:
        """A ticket for opening ``/ws/stream/?ticket=…``. Valid for a few seconds, once."""
        return Response(
            {
                "ticket": tickets.issue(current_user(request)),
                "expires_in": int(settings.WS_TICKET_TTL.total_seconds()),
            }
        )


urlpatterns = [
    path("auth/ws-ticket/", SocketTicketView.as_view(), name="auth-ws-ticket"),
]
