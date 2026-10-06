import pytest
from django.test import Client

from audit.models import ActorType, AppendOnlyError, AuditLog
from audit.services import record
from common import request_context
from users.models import User
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_record_captures_actor_target_and_request_context():
    actor, target = UserFactory(), UserFactory()
    request_context.bind(request_id="req-12345678", client_ip="203.0.113.9")
    try:
        entry = record(
            action="user.role_changed",
            target=target,
            actor=actor,
            metadata={"from": "USER", "to": "MODERATOR"},
        )
    finally:
        request_context.clear()

    entry.refresh_from_db()
    assert entry.actor == actor
    assert entry.actor_type == ActorType.USER
    assert entry.action == "user.role_changed"
    assert (entry.target_type, entry.target_id) == ("users.user", target.pk)
    assert entry.metadata == {"from": "USER", "to": "MODERATOR"}
    assert entry.ip == "203.0.113.9"
    assert entry.request_id == "req-12345678"


def test_system_actions_have_no_actor_and_no_ip():
    request_context.bind(request_id="req-12345678", client_ip="203.0.113.9")
    try:
        entry = record(action="opportunity.expired", target=UserFactory())
    finally:
        request_context.clear()

    assert entry.actor is None
    assert entry.actor_type == ActorType.SYSTEM
    assert entry.ip is None


def test_records_cannot_be_updated():
    entry = record(action="user.created", target=UserFactory())

    entry.action = "tampered"
    with pytest.raises(AppendOnlyError):
        entry.save()
    with pytest.raises(AppendOnlyError):
        AuditLog.objects.filter(pk=entry.pk).update(action="tampered")

    assert AuditLog.objects.get(pk=entry.pk).action == "user.created"


def test_records_cannot_be_deleted():
    entry = record(action="user.created", target=UserFactory())

    with pytest.raises(AppendOnlyError):
        entry.delete()
    with pytest.raises(AppendOnlyError):
        AuditLog.objects.all().delete()

    assert AuditLog.objects.filter(pk=entry.pk).exists()


def test_record_survives_deletion_of_actor_and_target():
    actor, target = UserFactory(), UserFactory()
    entry = record(action="user.suspended", target=target, actor=actor)
    target_id = target.pk

    actor.delete()
    target.delete()

    entry = AuditLog.objects.get(pk=entry.pk)
    assert entry.actor is None
    assert entry.target_id == target_id


def test_admin_is_read_only():
    admin = User.objects.create_superuser("root@example.com", "correct-horse-battery")
    entry = record(action="user.created", target=admin)
    client = Client()
    client.force_login(admin)

    assert client.get("/admin/audit/auditlog/").status_code == 200
    assert client.get("/admin/audit/auditlog/add/").status_code == 403
    delete_url = f"/admin/audit/auditlog/{entry.pk}/delete/"
    assert client.post(delete_url, {"post": "yes"}).status_code == 403
