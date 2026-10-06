import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(name="common.ping")
def ping() -> str:
    logger.info("ping")
    return "pong"
