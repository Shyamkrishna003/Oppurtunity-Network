from typing import Any

from rest_framework import serializers

from audit.models import AuditLog


class AuditActorSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    display_name = serializers.CharField(source="profile.display_name")


class AuditLogSerializer(serializers.ModelSerializer[AuditLog]):
    """An audit record as a tenant's owners see it: who did what to what, and when."""

    # Empty for something the system did by itself, or once the account is gone.
    actor = AuditActorSerializer(allow_null=True)

    class Meta:
        model = AuditLog
        fields: tuple[str, ...] = (
            "id",
            "action",
            "actor",
            "actor_type",
            "target_type",
            "target_id",
            "metadata",
            "created_at",
        )


class AdminAuditLogSerializer(AuditLogSerializer):
    """The same record for the platform's admins, with where it came from."""

    class Meta(AuditLogSerializer.Meta):
        fields = (
            *AuditLogSerializer.Meta.fields,
            "organization_id",
            "community_id",
            "ip",
            "request_id",
        )
