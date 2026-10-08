"""Token primitives. Nothing here touches the database."""

import hashlib
import secrets
from uuid import UUID

import jwt
from django.conf import settings
from django.core import signing
from django.utils import timezone
from django.utils.crypto import salted_hmac

from users.models import User

_ACCESS_ALGORITHM = "HS256"
_ACCESS_TYPE = "access"
_EMAIL_VERIFICATION_SALT = "users.email-verification"


class InvalidToken(Exception):
    pass


class ExpiredToken(InvalidToken):
    pass


def _access_key() -> bytes:
    # Derived from SECRET_KEY so access tokens cannot be confused with other signed values.
    return salted_hmac("users.access-token", "", algorithm="sha256").digest()


def make_access_token(user: User) -> tuple[str, int]:
    """Return ``(token, lifetime in seconds)``."""
    now = timezone.now()
    lifetime = settings.ACCESS_TOKEN_LIFETIME
    payload = {"sub": str(user.pk), "typ": _ACCESS_TYPE, "iat": now, "exp": now + lifetime}
    return jwt.encode(payload, _access_key(), algorithm=_ACCESS_ALGORITHM), int(
        lifetime.total_seconds()
    )


def read_access_token(token: str) -> UUID:
    """Return the user ID the token was issued to."""
    try:
        payload = jwt.decode(
            token,
            _access_key(),
            algorithms=[_ACCESS_ALGORITHM],
            options={"require": ["sub", "exp", "typ"]},
        )
        if payload["typ"] != _ACCESS_TYPE:
            raise InvalidToken
        return UUID(payload["sub"])
    except jwt.ExpiredSignatureError as exc:
        raise ExpiredToken from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise InvalidToken from exc


def new_refresh_token() -> tuple[str, str]:
    """Return ``(raw token for the cookie, hash to store)``."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    # The token is 48 random bytes, so a plain digest is enough; no salt or stretching needed.
    return hashlib.sha256(raw.encode()).hexdigest()


def make_email_verification_token(user: User) -> str:
    # Bound to the address, so it stops working if the email ever changes.
    return signing.dumps({"uid": str(user.pk), "email": user.email}, salt=_EMAIL_VERIFICATION_SALT)


def read_email_verification_token(token: str) -> tuple[UUID, str]:
    """Return ``(user ID, email)`` the token was issued for."""
    try:
        payload = signing.loads(
            token, salt=_EMAIL_VERIFICATION_SALT, max_age=settings.EMAIL_VERIFICATION_MAX_AGE
        )
        return UUID(payload["uid"]), str(payload["email"])
    except signing.SignatureExpired as exc:
        raise ExpiredToken from exc
    except (signing.BadSignature, KeyError, TypeError, ValueError) as exc:
        raise InvalidToken from exc
