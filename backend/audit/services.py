from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import models
from django.utils import timezone

from audit.models import ActorType, AuditLog
from common import request_context
from users.models import User


def record(
    *,
    action: str,
    target: models.Model,
    actor: User | None = None,
    organization_id: UUID | None = None,
    community_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Write an audit record. Call inside the transaction that performs the audited change.

    ``action`` is a namespaced verb such as ``application.status_changed``. ``actor`` is None
    for system-driven changes. Keep ``metadata`` free of secrets and message bodies.
    """
    return AuditLog.objects.create(
        actor=actor,
        actor_type=ActorType.USER if actor is not None else ActorType.SYSTEM,
        action=action,
        target_type=target._meta.label_lower,
        target_id=target.pk,
        organization_id=organization_id,
        community_id=community_id,
        metadata=metadata or {},
        ip=request_context.get_client_ip() if actor is not None else None,
        request_id=request_context.get_request_id(),
    )


def forget_old_ips() -> int:
    """Clear the address on records older than ``AUDIT_IP_RETENTION``. An address helps
    while an incident can still be looked into; after that it is personal data kept for no
    reason. The one change to a record that is allowed, here and by the database trigger.
    Returns how many records were cleared."""
    before = timezone.now() - settings.AUDIT_IP_RETENTION
    # Through the base manager: the model's own refuses every update, as it should.
    old = AuditLog._base_manager.filter(created_at__lt=before, ip__isnull=False)
    return old.update(ip=None)
