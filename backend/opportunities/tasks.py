import structlog
from celery import shared_task

from opportunities import services

logger = structlog.get_logger(__name__)


@shared_task(name="opportunities.expire_due")
def expire_due() -> int:
    """Periodic sweep. Applying and registering check the deadline themselves, so a late or
    missed run only delays the status label, never lets anyone in after the deadline."""
    expired = services.expire_due()
    logger.info("opportunities_expired", count=expired)
    return expired
