from collections.abc import Callable
from smtplib import SMTPException
from urllib.parse import urlencode

import structlog
from celery import Task, shared_task
from django.contrib.auth.tokens import default_token_generator
from django.utils import timezone

from common.email import send_templated
from users import tokens
from users.models import RefreshToken, User

logger = structlog.get_logger(__name__)


def _email_task(name: str) -> Callable[[Callable[[str], None]], Task[[str], None]]:
    """Tasks take a user ID and build the secret link when they run, so no token ever sits
    in the broker. A retry may send a duplicate email; that is acceptable (at-least-once)."""
    return shared_task(
        name=name,
        queue="email",
        autoretry_for=(SMTPException, OSError),
        retry_backoff=True,
        retry_backoff_max=600,
        retry_jitter=True,
        max_retries=6,
    )


@_email_task("users.send_verification_email")
def send_verification_email(user_id: str) -> None:
    user = User.objects.filter(pk=user_id, is_active=True, email_verified_at__isnull=True).first()
    if user is None:
        return
    query = urlencode({"token": tokens.make_email_verification_token(user)})
    send_templated(
        to=user.email,
        subject="Confirm your email address",
        template="users/email/verify_email.txt",
        context={"path": f"/verify-email?{query}"},
    )


@_email_task("users.send_password_reset_email")
def send_password_reset_email(user_id: str) -> None:
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return
    query = urlencode({"uid": str(user.pk), "token": default_token_generator.make_token(user)})
    send_templated(
        to=user.email,
        subject="Reset your password",
        template="users/email/password_reset.txt",
        context={"path": f"/reset-password?{query}"},
    )


@_email_task("users.send_account_exists_email")
def send_account_exists_email(user_id: str) -> None:
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return
    send_templated(
        to=user.email,
        subject="You already have an account",
        template="users/email/account_exists.txt",
        context={},
    )


@shared_task(name="users.purge_expired_refresh_tokens")
def purge_expired_refresh_tokens() -> int:
    deleted, _ = RefreshToken.objects.filter(expires_at__lt=timezone.now()).delete()
    logger.info("refresh_tokens_purged", count=deleted)
    return deleted
