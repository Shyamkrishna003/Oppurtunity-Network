import structlog
from celery import shared_task

from referrals import services

logger = structlog.get_logger(__name__)


@shared_task(name="referrals.sweep")
def sweep() -> int:
    """Periodic: expire unanswered requests, and close referrals for jobs that stopped
    taking applications. Asking, and making a referral, check the job themselves, so a late
    or missed run only delays a status label."""
    expired = services.expire_unanswered()
    closed = services.close_for_ended_jobs()
    logger.info("referrals_swept", expired=expired, closed=closed)
    return expired + closed
