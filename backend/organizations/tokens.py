"""Invitation tokens. Nothing here touches the database."""

import hashlib
from uuid import UUID

from django.utils.crypto import salted_hmac

_SALT = "organizations.invitation"


def invitation_token(invitation_id: UUID) -> str:
    """The secret that goes in the invitation link.

    Derived from the invitation ID with the server secret, so it cannot be guessed from the
    ID, and the email task can recompute it instead of carrying it through the broker.
    """
    return salted_hmac(_SALT, str(invitation_id), algorithm="sha256").hexdigest()


def hash_token(token: str) -> str:
    """What is stored and looked up, so a database leak does not expose usable links."""
    return hashlib.sha256(token.encode()).hexdigest()
