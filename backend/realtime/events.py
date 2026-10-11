"""Publishing events to connected browsers.

The socket is a hint, never the record. Whatever is published here already exists in
PostgreSQL and is reachable through the REST API; if the push is lost (no socket open, the
channel layer hiccups) the user sees it on their next request. So publishing is best-effort
and harmless to repeat: every event carries an ID the client uses to ignore duplicates.
"""

import uuid
from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

# Channel-layer message types. Channels turns "stream.event" into a call to the consumer's
# ``stream_event`` method, and "session.revoked" into ``session_revoked``.
STREAM_EVENT = "stream.event"
SESSION_REVOKED = "session.revoked"


def group_name(user_id: UUID | str) -> str:
    """The one group a user's sockets belong to. Derived on the server, never from a client."""
    return f"user.{user_id}"


def envelope(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": uuid.uuid4().hex,
        "type": event_type,
        "occurred_at": timezone.now().isoformat(),
        "data": data,
    }


def publish(user_id: UUID | str, event_type: str, data: dict[str, Any]) -> None:
    """Send an event to every socket the user has open. Call from a background task.

    Who receives what is decided by the caller, using the same rules as the REST API; the
    socket layer never decides visibility.
    """
    async_to_sync(get_channel_layer().group_send)(
        group_name(user_id), {"type": STREAM_EVENT, "event": envelope(event_type, data)}
    )


def revoke(user_id: UUID | str) -> None:
    """Close every socket the user has open. They reconnect only if they can still get a
    ticket, that is, if they still have a valid session."""
    async_to_sync(get_channel_layer().group_send)(group_name(user_id), {"type": SESSION_REVOKED})
