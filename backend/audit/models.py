from typing import Any, NoReturn

from django.conf import settings
from django.db import models

from common.models import UUIDModel


class AppendOnlyError(Exception):
    """Raised on any attempt to change or remove an audit record."""


class ActorType(models.TextChoices):
    USER = "USER", "User"
    SYSTEM = "SYSTEM", "System"


class AuditLogQuerySet(models.QuerySet["AuditLog"]):
    def update(self, **kwargs: Any) -> NoReturn:
        raise AppendOnlyError("Audit records cannot be updated.")

    def delete(self) -> NoReturn:
        raise AppendOnlyError("Audit records cannot be deleted.")


class AuditLog(UUIDModel):
    """Append-only record of a security-sensitive action.

    The target is a loose ``(target_type, target_id)`` reference rather than a foreign key,
    so the record survives deletion of the thing it describes.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    actor_type = models.CharField(max_length=8, choices=ActorType.choices)
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=64)
    target_id = models.UUIDField()
    # Tenant scope, so organization/community owners can read their own trail.
    organization_id = models.UUIDField(null=True, blank=True)
    community_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(actor_type__in=ActorType.values),
                name="audit_auditlog_actor_type_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["target_type", "target_id", "created_at"]),
            models.Index(fields=["actor", "created_at"]),
            models.Index(fields=["organization_id", "created_at"]),
            models.Index(fields=["community_id", "created_at"]),
            models.Index(fields=["action", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.target_type}:{self.target_id}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnlyError("Audit records cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise AppendOnlyError("Audit records cannot be deleted.")
