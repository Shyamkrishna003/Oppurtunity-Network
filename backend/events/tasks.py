from uuid import UUID

import structlog
from celery import shared_task

from events import registrations, reminders, services

logger = structlog.get_logger(__name__)


@shared_task(name="events.advance_states")
def advance_states() -> dict[str, int]:
    """Periodic sweep: opens and closes registration and completes events as time passes."""
    moved = services.advance_states()
    logger.info("events_advanced", **moved)
    return moved


@shared_task(name="events.send_reminders")
def send_reminders() -> dict[str, int]:
    """Periodic sweep: reminds people the day before and an hour before an event starts."""
    sent = reminders.send_due()
    logger.info("event_reminders_sent", **{f"lead_{key}": count for key, count in sent.items()})
    return sent


@shared_task(
    name="events.announce_cancellation",
    queue="notifications",
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=True,
    max_retries=3,
)
def announce_cancellation(opportunity_id: str) -> int:
    """Tell everyone registered that the event is off. Safe to retry: each person is told once."""
    told = registrations.announce_cancellation(UUID(opportunity_id))
    logger.info("event_cancellation_announced", opportunity_id=opportunity_id, count=told)
    return told
