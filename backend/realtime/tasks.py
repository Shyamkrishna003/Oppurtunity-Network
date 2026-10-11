"""An HTTP request never talks to sockets itself: it queues one of these after committing.

Three quick retries cover a channel-layer blip; after that the push is dropped, which is
safe because whatever it announced is already stored and reachable through the API.
"""

from typing import Any

from celery import shared_task

from realtime import events


@shared_task(
    name="realtime.publish_event",
    queue="notifications",
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=2,
    retry_backoff_max=10,
    max_retries=3,
)
def publish_event(user_id: str, event_type: str, data: dict[str, Any]) -> None:
    events.publish(user_id, event_type, data)


@shared_task(
    name="realtime.revoke_sessions",
    queue="notifications",
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=2,
    retry_backoff_max=10,
    max_retries=3,
)
def revoke_sessions(user_id: str) -> None:
    events.revoke(user_id)
