import structlog
from celery import shared_task

from events import services

logger = structlog.get_logger(__name__)


@shared_task(name="events.advance_states")
def advance_states() -> dict[str, int]:
    """Periodic sweep: opens and closes registration and completes events as time passes."""
    moved = services.advance_states()
    logger.info("events_advanced", **moved)
    return moved
