"""Single-use tickets for opening the WebSocket.

A browser cannot set an ``Authorization`` header on a WebSocket, and the access token must
not appear in a URL (URLs end up in logs and history). So a signed-in client asks for a
ticket over the normal API and presents it once, within seconds, in the socket's query
string. A leaked ticket is worthless almost immediately and can never be used twice.

Tickets live in the cache (Redis). Losing them is harmless: the client asks for another.
"""

import secrets
from uuid import UUID

from django.conf import settings
from django.core.cache import cache

from users.models import User


def _key(ticket: str) -> str:
    return f"ws:ticket:{ticket}"


def issue(user: User) -> str:
    ticket = secrets.token_urlsafe(32)
    cache.set(_key(ticket), str(user.pk), timeout=int(settings.WS_TICKET_TTL.total_seconds()))
    return ticket


def redeem(ticket: str) -> UUID | None:
    """The user the ticket was issued to, or ``None``. Works once per ticket.

    The delete decides the winner: if two connections present the same ticket at the same
    moment, both may read it, but only one delete reports having removed it.
    """
    # Bounded, so a junk query string cannot become an arbitrarily long cache key.
    if not ticket or len(ticket) > 64:
        return None
    user_id = cache.get(_key(ticket))
    if user_id is None or not cache.delete(_key(ticket)):
        return None
    return UUID(user_id)
