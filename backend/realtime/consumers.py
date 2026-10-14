import asyncio
import contextlib
import json
import time
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs
from uuid import UUID

import structlog
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.utils import timezone

from realtime import tickets
from realtime.events import envelope, group_name
from users.models import User

logger = structlog.get_logger(__name__)

# Application close codes (4000-4999 are ours to define). The client reacts differently to
# each: 4401 means "get a new ticket", which only works with a valid session.
CLOSE_UNAUTHENTICATED = 4401
CLOSE_IDLE = 4408
CLOSE_TOO_LARGE = 1009

# Clients only ever send heartbeats, so anything large is not a heartbeat.
_MAX_INCOMING_BYTES = 256


def _authenticate(ticket: str) -> UUID | None:
    user_id = tickets.redeem(ticket)
    if user_id is None:
        return None
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None or user.is_suspended:
        return None
    return user_id


class StreamConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc]  # channels is untyped
    """One socket per browser tab, carrying everything the server pushes to that user.

    Server to client only. A client cannot subscribe to anything: the socket joins exactly
    one group, named after the authenticated user. What goes into that group is decided
    elsewhere, by the same rules that guard the REST API.
    """

    user_id: UUID | None = None
    _watchdog: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        query = parse_qs(self.scope["query_string"].decode("ascii", errors="ignore"))
        user_id = await database_sync_to_async(_authenticate)(query.get("ticket", [""])[0])

        # A close code can only be delivered on an accepted socket; rejecting the handshake
        # would give the client a bare failure it could not tell from a network error.
        await self.accept()
        if user_id is None:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        self.user_id = user_id
        await self.channel_layer.group_add(group_name(user_id), self.channel_name)
        self._opened = self._last_heard = time.monotonic()
        self._watchdog = asyncio.create_task(self._watch())
        expires = timezone.now() + settings.WS_SESSION_MAX_AGE
        await self.send_json(
            envelope(
                "hello",
                {
                    "server_time": timezone.now().isoformat(),
                    "session_expires_at": expires.isoformat(),
                    "heartbeat_seconds": int(settings.WS_HEARTBEAT.total_seconds()),
                },
            )
        )
        logger.info("socket_opened", user_id=str(user_id))

    async def disconnect(self, code: int) -> None:
        if self._watchdog is not None:
            self._watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog
        if self.user_id is not None:
            await self.channel_layer.group_discard(group_name(self.user_id), self.channel_name)
            logger.info("socket_closed", user_id=str(self.user_id), code=code)

    async def receive(
        self, text_data: str | None = None, bytes_data: bytes | None = None, **kwargs: Any
    ) -> None:
        if self.user_id is None:
            return
        if bytes_data is not None or len(text_data or "") > _MAX_INCOMING_BYTES:
            await self.close(code=CLOSE_TOO_LARGE)
            return
        # Any traffic shows the client is alive, well-formed or not.
        self._last_heard = time.monotonic()
        try:
            message = json.loads(text_data or "")
        except ValueError:
            return
        if isinstance(message, dict) and message.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def _watch(self) -> None:
        """Close the socket when the session cap is reached or the client goes silent."""
        idle_limit = settings.WS_IDLE_TIMEOUT.total_seconds()
        max_age = settings.WS_SESSION_MAX_AGE.total_seconds()
        interval = min(idle_limit, max_age, timedelta(seconds=5).total_seconds()) / 2
        while True:
            await asyncio.sleep(interval)
            now = time.monotonic()
            if now - self._opened >= max_age:
                # Not an error: the client fetches a new ticket and comes straight back,
                # which re-checks that its session is still valid.
                await self.close(code=CLOSE_UNAUTHENTICATED)
                return
            if now - self._last_heard >= idle_limit:
                await self.close(code=CLOSE_IDLE)
                return

    # --- Messages from the channel layer --------------------------------------------------

    async def stream_event(self, message: dict[str, Any]) -> None:
        await self.send_json(message["event"])

    async def session_revoked(self, message: dict[str, Any]) -> None:
        await self.close(code=CLOSE_UNAUTHENTICATED)
