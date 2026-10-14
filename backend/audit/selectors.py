"""Read queries for the audit trail. Who may read which part is decided by the caller."""

from collections.abc import Iterable
from uuid import UUID

from django.db.models import Q, QuerySet

from audit.models import AuditLog


def search(
    *,
    actor_id: UUID | None = None,
    action: str = "",
    target_type: str = "",
    target_id: UUID | None = None,
    organization_id: UUID | None = None,
    community_id: UUID | None = None,
    kinds: Iterable[str] = (),
) -> QuerySet[AuditLog]:
    """Audit records matching every filter given.

    ``action`` matches a whole action or the start of one, so ``"report."`` finds everything
    about reports. ``kinds`` limits the result to actions starting with any of the given
    prefixes: a tenant's owners are shown a chosen part of what is filed under their tenant,
    never all of it.
    """
    records = AuditLog.objects.select_related("actor__profile")
    if actor_id is not None:
        records = records.filter(actor_id=actor_id)
    if action:
        records = records.filter(action__startswith=action)
    if target_type:
        records = records.filter(target_type=target_type)
    if target_id is not None:
        records = records.filter(target_id=target_id)
    if organization_id is not None:
        records = records.filter(organization_id=organization_id)
    if community_id is not None:
        records = records.filter(community_id=community_id)
    prefixes = tuple(kinds)
    if prefixes:
        allowed = Q()
        for prefix in prefixes:
            allowed |= Q(action__startswith=prefix)
        records = records.filter(allowed)
    return records
