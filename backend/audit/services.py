from typing import Any
from uuid import UUID

from django.db import models

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
