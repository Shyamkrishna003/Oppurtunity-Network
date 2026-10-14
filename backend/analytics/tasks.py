from datetime import date
from uuid import UUID

import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(name="analytics.record_view", queue="analytics", ignore_result=True)
def record_view(opportunity_id: str, day: str) -> None:
    """Add one view. Never retried: see ``services.add_view``."""
    from analytics import services

    services.add_view(UUID(opportunity_id), date.fromisoformat(day))


@shared_task(name="analytics.refresh_stats", queue="analytics")
def refresh_stats() -> int:
    """Periodic rebuild of every published opportunity's numbers. A missed run only means
    the "popular" order is a little out of date."""
    from analytics import services

    refreshed = services.refresh()
    logger.info("opportunity_stats_refreshed", count=refreshed)
    return refreshed
