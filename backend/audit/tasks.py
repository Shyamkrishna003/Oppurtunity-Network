import structlog
from celery import shared_task

from audit import services

logger = structlog.get_logger(__name__)


@shared_task(name="audit.forget_old_ips")
def forget_old_ips() -> int:
    """Daily. Running it twice, or late, changes nothing more."""
    cleared = services.forget_old_ips()
    logger.info("audit_ips_forgotten", count=cleared)
    return cleared
