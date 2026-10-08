"""Account and session operations. Views call these; nothing else changes auth state."""

import hashlib
from dataclasses import dataclass
from functools import partial
from uuid import UUID

import structlog
from celery import Task
from django.conf import settings
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.hashers import make_password
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from kombu.exceptions import OperationalError
from rest_framework.exceptions import Throttled

from audit.services import record
from common.errors import BadRequest, BusinessRuleViolation
from users import tasks, tokens
from users.errors import InvalidCredentials, SessionExpired
from users.models import RefreshToken, User, UserManager

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Session:
    user: User
    access_token: str
    expires_in: int
    refresh_token: str


def _validate_password(password: str, user: User, field: str) -> None:
    try:
        password_validation.validate_password(password, user)
    except DjangoValidationError as exc:
        raise BusinessRuleViolation(
            "Choose a stronger password.", code="weak_password", errors={field: exc.messages}
        ) from exc


def _enqueue_email(task: Task[[str], None], user: User) -> None:
    """Queue an email. A broker outage is logged, not raised: the account change it follows
    has already happened, and every one of these emails can be requested again."""
    try:
        task.delay(str(user.pk))
    except OperationalError:
        logger.exception("email_enqueue_failed", task=task.name, user_id=str(user.pk))


def register(*, email: str, password: str, display_name: str) -> None:
    """Create an account and send the verification email.

    Returns nothing and behaves the same whether or not the address is already registered,
    so the endpoint cannot be used to discover who has an account.
    """
    email = UserManager.normalize_email(email)
    _validate_password(password, User(email=email), "password")

    existing = User.objects.filter(email=email).first()
    if existing is None:
        try:
            with transaction.atomic():
                user = User.objects.create_user(email, password, display_name=display_name)
                record(action="user.registered", target=user, actor=user)
                transaction.on_commit(partial(_enqueue_email, tasks.send_verification_email, user))
            return
        except IntegrityError:
            # Lost a race with a concurrent registration for the same address.
            existing = User.objects.filter(email=email).first()
    else:
        make_password(password)  # keep response time comparable to the new-account path

    if existing is None or not existing.is_active:
        return
    if existing.is_email_verified:
        _enqueue_email(tasks.send_account_exists_email, existing)
    else:
        _enqueue_email(tasks.send_verification_email, existing)


def resend_verification(*, email: str) -> None:
    user = User.objects.filter(
        email=UserManager.normalize_email(email), is_active=True, email_verified_at__isnull=True
    ).first()
    if user is not None:
        _enqueue_email(tasks.send_verification_email, user)


def verify_email(*, token: str) -> None:
    """Idempotent: confirming an already confirmed address succeeds without effect."""
    try:
        user_id, email = tokens.read_email_verification_token(token)
    except tokens.ExpiredToken as exc:
        raise BadRequest("This link has expired. Request a new one.", code="token_expired") from exc
    except tokens.InvalidToken as exc:
        raise BadRequest("This link is not valid.", code="token_invalid") from exc

    with transaction.atomic():
        # Conditional update: of two concurrent requests only one records the change.
        updated = User.objects.filter(
            pk=user_id, email=email, is_active=True, email_verified_at__isnull=True
        ).update(email_verified_at=timezone.now())
        if updated:
            user = User.objects.get(pk=user_id)
            record(action="user.email_verified", target=user, actor=user)
        elif not User.objects.filter(pk=user_id, email=email, is_active=True).exists():
            raise BadRequest("This link is not valid.", code="token_invalid")


def _failure_key(email: str) -> str:
    return "auth:login-failures:" + hashlib.sha256(email.encode()).hexdigest()


def _check_not_locked(email: str) -> None:
    if cache.get(_failure_key(email), 0) >= settings.LOGIN_FAILURE_LIMIT:
        raise Throttled(
            wait=settings.LOGIN_FAILURE_WINDOW.total_seconds(),
            detail="Too many failed sign-in attempts. Try again later or reset your password.",
        )


def _count_failure(email: str) -> None:
    key = _failure_key(email)
    # add() is a no-op when the key exists, so the window starts at the first failure.
    cache.add(key, 0, timeout=int(settings.LOGIN_FAILURE_WINDOW.total_seconds()))
    try:
        cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, timeout=int(settings.LOGIN_FAILURE_WINDOW.total_seconds()))


def login(*, email: str, password: str) -> Session:
    email = UserManager.normalize_email(email)
    # Counted per address (whether or not it has an account), on top of the per-IP throttle.
    _check_not_locked(email)

    user = authenticate(username=email, password=password)
    if not isinstance(user, User):
        _count_failure(email)
        logger.warning("login_failed")
        raise InvalidCredentials()

    cache.delete(_failure_key(email))
    with transaction.atomic():
        User.objects.filter(pk=user.pk).update(last_login=timezone.now())
        record(action="user.logged_in", target=user, actor=user)
        return _start_session(user)


def _issue_refresh_token(user: User, family: UUID | None = None) -> str:
    raw, token_hash = tokens.new_refresh_token()
    token = RefreshToken(
        user=user,
        token_hash=token_hash,
        expires_at=timezone.now() + settings.REFRESH_TOKEN_LIFETIME,
    )
    if family is not None:
        token.family = family
    token.save()
    return raw


def _start_session(user: User, family: UUID | None = None) -> Session:
    access_token, expires_in = tokens.make_access_token(user)
    return Session(
        user=user,
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=_issue_refresh_token(user, family),
    )


def refresh(*, refresh_token: str) -> Session:
    """Exchange a refresh token for a new access token and the next refresh token.

    Each refresh token works once. Presenting one that was already exchanged means it was
    copied, so every token descended from the same login is revoked.
    """
    now = timezone.now()
    with transaction.atomic():
        # The row lock makes concurrent exchanges of one token run one after the other.
        token = (
            RefreshToken.objects.select_for_update(of=("self",))
            .select_related("user")
            .filter(token_hash=tokens.hash_refresh_token(refresh_token))
            .first()
        )
        if (
            token is None
            or token.revoked_at is not None
            or token.expires_at <= now
            or not token.user.is_active
        ):
            raise SessionExpired()

        if token.rotated_at is None:
            token.rotated_at = now
            token.save(update_fields=["rotated_at"])
            return _start_session(token.user, token.family)
        if now - token.rotated_at <= settings.REFRESH_TOKEN_REUSE_GRACE:
            # Another tab refreshed a moment ago with the same token.
            return _start_session(token.user, token.family)

        # Reuse. Revoke inside this transaction and let it commit before failing the request.
        RefreshToken.objects.filter(family=token.family, revoked_at__isnull=True).update(
            revoked_at=now
        )
        record(
            action="user.refresh_token_reused",
            target=token.user,
            metadata={"family": str(token.family)},
        )
    logger.warning("refresh_token_reused", user_id=str(token.user_id))
    raise SessionExpired()


def logout(*, refresh_token: str) -> None:
    """Ends the session the token belongs to. Unknown or already ended tokens are ignored."""
    with transaction.atomic():
        token = (
            RefreshToken.objects.select_related("user")
            .filter(token_hash=tokens.hash_refresh_token(refresh_token))
            .first()
        )
        if token is None:
            return
        revoked = RefreshToken.objects.filter(family=token.family, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        if revoked:
            record(action="user.logged_out", target=token.user, actor=token.user)


def _revoke_all_sessions(user: User) -> None:
    RefreshToken.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def request_password_reset(*, email: str) -> None:
    """Same outcome for known and unknown addresses; see ``register``."""
    user = User.objects.filter(email=UserManager.normalize_email(email), is_active=True).first()
    if user is None:
        return
    record(action="user.password_reset_requested", target=user)
    _enqueue_email(tasks.send_password_reset_email, user)


def confirm_password_reset(*, uid: str, token: str, new_password: str) -> None:
    invalid = BadRequest(
        "This link is not valid or has expired. Request a new one.", code="token_invalid"
    )
    try:
        user_id = UUID(uid)
    except ValueError as exc:
        raise invalid from exc

    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=user_id, is_active=True).first()
        # The token is derived from the password hash, so it stops working once used.
        if user is None or not default_token_generator.check_token(user, token):
            raise invalid
        _validate_password(new_password, user, "new_password")
        user.set_password(new_password)
        # Completing a reset proves control of the mailbox.
        if user.email_verified_at is None:
            user.email_verified_at = timezone.now()
        user.save(update_fields=["password", "email_verified_at", "updated_at"])
        _revoke_all_sessions(user)
        record(action="user.password_reset", target=user, actor=user)
    cache.delete(_failure_key(user.email))


def change_password(*, user: User, current_password: str, new_password: str) -> Session:
    """Sets a new password, ends every session, and starts a fresh one for the caller."""
    if not user.check_password(current_password):
        raise BusinessRuleViolation(
            "Your current password is incorrect.",
            code="incorrect_password",
            errors={"current_password": ["Your current password is incorrect."]},
        )
    _validate_password(new_password, user, "new_password")
    with transaction.atomic():
        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])
        _revoke_all_sessions(user)
        record(action="user.password_changed", target=user, actor=user)
        return _start_session(user)
