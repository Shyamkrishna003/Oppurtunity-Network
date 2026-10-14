"""The database itself refuses to rewrite the audit trail, whatever the code does."""

from datetime import timedelta
from unittest import mock

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from audit import services, tasks
from audit.models import AuditLog
from common import request_context
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def entry_from(ip="203.0.113.9", **fields) -> AuditLog:
    request_context.bind(request_id="req-12345678", client_ip=ip)
    try:
        return services.record(action="user.role_changed", target=UserFactory.create(), **fields)
    finally:
        request_context.clear()


def run(sql: str, *params) -> None:
    """A statement straight to the database, past the model and its manager."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(sql, params)


@pytest.mark.parametrize(
    "change",
    [
        "action = 'tampered'",
        'metadata = \'{"to": "ADMIN"}\'',
        "target_id = gen_random_uuid()",
        "created_at = now() - interval '1 year'",
        "actor_type = 'SYSTEM'",
        "request_id = ''",
        "organization_id = gen_random_uuid()",
        "ip = '198.51.100.1'",
    ],
)
def test_the_database_refuses_to_change_a_record(change):
    entry = entry_from(actor=UserFactory.create())

    with pytest.raises(IntegrityError, match="append-only"):
        run(f"UPDATE audit_auditlog SET {change} WHERE id = %s", entry.pk)  # noqa: S608

    kept = AuditLog.objects.get(pk=entry.pk)
    assert (kept.action, kept.ip, kept.created_at) == (entry.action, entry.ip, entry.created_at)


def test_the_database_refuses_to_delete_a_record_or_to_swap_who_did_it():
    actor, other = UserFactory.create(), UserFactory.create()
    entry = entry_from(actor=actor)

    with pytest.raises(IntegrityError, match="append-only"):
        run("DELETE FROM audit_auditlog WHERE id = %s", entry.pk)
    with pytest.raises(IntegrityError, match="append-only"):
        run("UPDATE audit_auditlog SET actor_id = %s WHERE id = %s", other.pk, entry.pk)
    # Not even through the base manager, which skips the model's own refusal.
    with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
        AuditLog._base_manager.filter(pk=entry.pk).update(action="tampered")
    with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
        AuditLog._base_manager.filter(pk=entry.pk).delete()

    assert AuditLog.objects.get(pk=entry.pk).actor == actor


def test_deleting_an_account_still_only_blanks_who_did_it():
    actor = UserFactory.create()
    entry = entry_from(actor=actor)

    actor.delete()

    kept = AuditLog.objects.get(pk=entry.pk)
    assert (kept.actor, kept.action, kept.actor_type) == (None, "user.role_changed", "USER")


def test_old_addresses_are_forgotten_and_nothing_else_changes(settings):
    settings.AUDIT_IP_RETENTION = timedelta(days=90)
    actor = UserFactory.create()
    # Written as if 91 days ago: a record cannot be backdated once it exists.
    long_ago = timezone.now() - timedelta(days=91)
    with mock.patch("django.utils.timezone.now", return_value=long_ago):
        old = entry_from(actor=actor)
        entry_from(ip=None, actor=actor)
    recent = entry_from(actor=actor)
    assert AuditLog.objects.get(pk=old.pk).created_at == long_ago

    assert tasks.forget_old_ips() == 1
    assert tasks.forget_old_ips() == 0  # again changes nothing

    cleared = AuditLog.objects.get(pk=old.pk)
    assert cleared.ip is None
    assert (cleared.actor, cleared.action, cleared.request_id) == (
        actor,
        "user.role_changed",
        "req-12345678",
    )
    assert AuditLog.objects.get(pk=recent.pk).ip == "203.0.113.9"
