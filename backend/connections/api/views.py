from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from common.throttles import ScopedThrottle
from connections import selectors, services
from connections.api import serializers
from connections.models import Connection
from connections.policies import State
from users.api.utils import current_user
from users.permissions import IsVerified

STATES = [state.value for state in State]


def _one(request: Request, connection: Connection, status_code: int = 200) -> Response:
    context = {"viewer_id": current_user(request).pk}
    data = serializers.ConnectionSerializer(connection, context=context).data
    return Response(data, status=status_code)


class ConnectionListView(generics.ListAPIView[Connection]):
    """The caller's own connections (the default), or the requests on one side.

    Nobody else's connections can be listed, by any parameter.
    """

    serializer_class = serializers.ConnectionSerializer
    throttle_scope = "connection_request"

    def get_permissions(self) -> list[BasePermission]:
        return [IsVerified()] if self.request.method == "POST" else [IsAuthenticated()]

    def get_throttles(self) -> list[BaseThrottle]:
        return [ScopedThrottle()] if self.request.method == "POST" else []

    def get_queryset(self) -> QuerySet[Connection]:
        if getattr(self, "swagger_fake_view", False):
            return Connection.objects.none()
        requested = self.request.query_params.get("state", State.CONNECTED.value)
        if requested not in STATES:
            raise ValidationError({"state": [f"Choose one of: {', '.join(STATES)}."]})
        return selectors.list_for(current_user(self.request), State(requested))

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "viewer_id": self.request.user.pk}

    @extend_schema(parameters=[OpenApiParameter("state", str, enum=STATES)])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=serializers.ConnectionRequestSerializer,
        responses={
            201: serializers.ConnectionSerializer,
            200: serializers.ConnectionSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        """Ask someone to connect.

        Answers 201 for a new request, and 200 with the request already out if the caller
        has asked this person before. 409 ``already_connected`` or ``request_waiting`` (they
        asked first: answer that instead). 404 for someone who does not exist, is
        deactivated, or is blocked in either direction.
        """
        serializer = serializers.ConnectionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        connection, created = services.request(
            user=current_user(request), user_id=serializer.validated_data["user_id"]
        )
        return _one(request, connection, status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class ConnectionSummaryView(APIView):
    @extend_schema(responses=serializers.ConnectionSummarySerializer)
    def get(self, request: Request) -> Response:
        """How many requests are waiting for the caller's answer."""
        return Response({"incoming": selectors.incoming_count(current_user(request))})


class ConnectionDetailView(APIView):
    @extend_schema(responses={204: None})
    def delete(self, request: Request, connection_id: UUID) -> Response:
        """End a connection, or take back a request the caller made.

        409 ``answer_instead`` for a request made to the caller: accept or decline it.
        """
        services.remove(user=current_user(request), connection_id=connection_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AcceptView(APIView):
    @extend_schema(request=None, responses=serializers.ConnectionSerializer)
    def post(self, request: Request, connection_id: UUID) -> Response:
        """Accept a request made to the caller."""
        connection = services.respond(
            user=current_user(request), connection_id=connection_id, accept=True
        )
        return _one(request, connection)


class DeclineView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, connection_id: UUID) -> Response:
        """Decline a request made to the caller. The person who asked is not told."""
        services.respond(user=current_user(request), connection_id=connection_id, accept=False)
        return Response(status=status.HTTP_204_NO_CONTENT)
