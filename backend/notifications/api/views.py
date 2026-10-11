from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications import services
from notifications.api import serializers
from notifications.models import Category, Notification
from users.api.utils import current_user
from users.models import User


class NotificationListView(generics.ListAPIView[Notification]):
    """The caller's notifications, newest first. ``?unread=true`` for unread ones only."""

    serializer_class = serializers.NotificationSerializer

    def get_queryset(self) -> QuerySet[Notification]:
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        unread_only = self.request.query_params.get("unread", "").lower() == "true"
        return services.list_for(current_user(self.request), unread_only=unread_only)

    @extend_schema(parameters=[OpenApiParameter("unread", bool)])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class UnreadCountView(APIView):
    @extend_schema(responses=serializers.UnreadCountSerializer)
    def get(self, request: Request) -> Response:
        """How many notifications are unread, for the badge."""
        return Response({"count": services.unread_count(current_user(request))})


class MarkReadView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, notification_id: UUID) -> Response:
        """Mark one notification as read. Repeating it changes nothing."""
        services.mark_read(user=current_user(request), notification_id=notification_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MarkAllReadView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        services.mark_all_read(user=current_user(request))
        return Response(status=status.HTTP_204_NO_CONTENT)


def _preferences(user: User) -> list[dict[str, Any]]:
    return [
        {"category": category, "in_app": in_app, "email": email}
        for category, (in_app, email) in services.preferences_for(user).items()
    ]


class PreferencesView(APIView):
    @extend_schema(responses=serializers.PreferencesSerializer)
    def get(self, request: Request) -> Response:
        """Every category with the caller's choice, or the default where they made none."""
        data = {"preferences": _preferences(current_user(request))}
        return Response(serializers.PreferencesSerializer(data).data)

    @extend_schema(
        request=serializers.PreferencesSerializer, responses=serializers.PreferencesSerializer
    )
    def put(self, request: Request) -> Response:
        """Set the choice for the categories given; others are left as they are."""
        user = current_user(request)
        serializer = serializers.PreferencesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_preferences(
            user=user,
            choices={
                Category(item["category"]): (item["in_app"], item["email"])
                for item in serializer.validated_data["preferences"]
            },
        )
        data = {"preferences": _preferences(user)}
        return Response(serializers.PreferencesSerializer(data).data)
