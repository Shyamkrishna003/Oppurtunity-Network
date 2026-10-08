from datetime import timedelta
from smtplib import SMTPException

import pytest
from celery.exceptions import Retry
from django.core import mail
from django.utils import timezone
from kombu.exceptions import OperationalError

from users import tasks
from users.models import RefreshToken, User
from users.services import auth
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_verification_email_links_to_the_web_app():
    user = UserFactory(unverified=True)

    tasks.send_verification_email(str(user.pk))

    (message,) = mail.outbox
    assert message.to == [user.email]
    assert "http://app.test/verify-email?token=" in message.body


def test_verification_email_is_skipped_once_verified_or_deactivated():
    tasks.send_verification_email(str(UserFactory().pk))
    tasks.send_verification_email(str(UserFactory(unverified=True, is_active=False).pk))

    assert mail.outbox == []


def test_password_reset_email_links_to_the_web_app():
    user = UserFactory()

    tasks.send_password_reset_email(str(user.pk))

    assert f"http://app.test/reset-password?uid={user.pk}&token=" in mail.outbox[0].body


def test_email_tasks_retry_when_the_mail_server_fails(monkeypatch):
    def fail(**kwargs):
        raise SMTPException("mail server down")

    monkeypatch.setattr(tasks, "send_templated", fail)
    user = UserFactory(unverified=True)

    with pytest.raises(Retry):
        tasks.send_verification_email.apply(args=[str(user.pk)], throw=True)


def test_registration_survives_a_broker_outage(
    api, monkeypatch, django_capture_on_commit_callbacks
):
    def fail(*args, **kwargs):
        raise OperationalError("broker down")

    monkeypatch.setattr(tasks.send_verification_email, "delay", fail)

    with django_capture_on_commit_callbacks(execute=True):
        auth.register(email="ada@example.com", password="correct-horse-battery", display_name="Ada")

    assert User.objects.filter(email="ada@example.com").exists()


def test_purge_removes_only_expired_refresh_tokens():
    user = UserFactory()
    now = timezone.now()
    live = RefreshToken.objects.create(
        user=user, token_hash="a" * 64, expires_at=now + timedelta(days=1)
    )
    RefreshToken.objects.create(user=user, token_hash="b" * 64, expires_at=now - timedelta(days=1))

    assert tasks.purge_expired_refresh_tokens() == 1
    assert list(RefreshToken.objects.all()) == [live]
