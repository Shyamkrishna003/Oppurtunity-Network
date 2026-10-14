from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from audit import selectors
from audit.api import serializers
from audit.models import AuditLog
from users.models import User
from users.policies import is_platform_admin


class IsPlatformAdmin(BasePermission):
    """A platform admin. Moderators, and roles inside a tenant, do not count."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return isinstance(user, User) and is_platform_admin(user)


def _uuid(request: Request, name: str) -> UUID | None:
    value = request.query_params.get(name, "")
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValidationError({name: ["Not a valid id."]}) from exc


class AuditLogView(generics.ListAPIView[AuditLog]):
    """The whole audit trail, newest first, for the platform's admins."""

    permission_classes = [IsPlatformAdmin]
    serializer_class = serializers.AdminAuditLogSerializer

    def get_queryset(self) -> QuerySet[AuditLog]:
        if getattr(self, "swagger_fake_view", False):
            return AuditLog.objects.none()
        params = self.request.query_params
        actor_id = _uuid(self.request, "actor")
        email = params.get("actor_email", "").strip().lower()
        if email:
            # Emails are stored lowercased. An address nobody has finds nothing.
            found = User.objects.filter(email=email).values_list("pk", flat=True).first()
            if found is None:
                return AuditLog.objects.none()
            actor_id = found
        return selectors.search(
            actor_id=actor_id,
            action=params.get("action", "").strip()[:64],
            target_type=params.get("target_type", "").strip()[:64],
            target_id=_uuid(self.request, "target_id"),
            organization_id=_uuid(self.request, "organization_id"),
            community_id=_uuid(self.request, "community_id"),
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("actor", str, description="Id of whoever did it."),
            OpenApiParameter("actor_email", str, description="Their email address, in full."),
            OpenApiParameter(
                "action", str, description='An action, or the start of one: "report."'
            ),
            OpenApiParameter("target_type", str, description='Such as "users.user".'),
            OpenApiParameter("target_id", str),
            OpenApiParameter("organization_id", str),
            OpenApiParameter("community_id", str),
        ]
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)
