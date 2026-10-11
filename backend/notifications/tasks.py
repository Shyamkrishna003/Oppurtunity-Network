from datetime import timedelta
from smtplib import SMTPException

import structlog
from celery import shared_task
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from common.email import send_templated
from common.tasks import enqueue
from notifications.catalog import render
from notifications.models import Channel, DeliveryStatus, Notification, NotificationDelivery

logger = structlog.get_logger(__name__)

MAX_ATTEMPTS = 6
# A delivery this old and still pending was not picked up (queue outage, worker restart).
REDISPATCH_AFTER = timedelta(minutes=5)
REDISPATCH_BATCH = 200
# Read notifications are kept this long; unread ones are never purged.
KEEP_READ_FOR = timedelta(days=90)


@shared_task(
    name="notifications.send_notification_email",
    queue="email",
    autoretry_for=(SMTPException, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=MAX_ATTEMPTS - 1,
)
def send_notification_email(delivery_id: str) -> str:
    """Send one notification by email. Safe to queue more than once for the same delivery.

    The delivery row is locked for the duration: a second copy of this task finds it locked
    (or already sent) and does nothing. If sending fails the transaction rolls back, the row
    stays pending, and Celery or the redispatch sweep tries again.
    """
    # Counted first and outside the lock, so that failed attempts are remembered.
    NotificationDelivery.objects.filter(pk=delivery_id, status=DeliveryStatus.PENDING).update(
        attempts=F("attempts") + 1
    )
    with transaction.atomic():
        delivery = (
            NotificationDelivery.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("notification__recipient")
            .filter(pk=delivery_id, status=DeliveryStatus.PENDING, channel=Channel.EMAIL)
            .first()
        )
        if delivery is None:
            return "nothing to do"
        notification = delivery.notification
        recipient = notification.recipient
        if not recipient.is_active or not recipient.is_email_verified:
            delivery.status = DeliveryStatus.SKIPPED
            delivery.save(update_fields=["status"])
            return "skipped"

        rendered = render(notification)
        send_templated(
            to=recipient.email,
            subject=rendered.title,
            template="notifications/email/notification.txt",
            context={"title": rendered.title, "body": rendered.body, "path": rendered.url},
        )
        delivery.status = DeliveryStatus.SENT
        delivery.sent_at = timezone.now()
        delivery.save(update_fields=["status", "sent_at"])
        return "sent"


@shared_task(name="notifications.redispatch_pending")
def redispatch_pending() -> int:
    """Queue again what should have been sent by now, and give up on what keeps failing.

    This is what makes email delivery survive a broker outage or a worker restart: the
    pending row in the database is the source of truth, not the message in the queue.
    """
    stale = NotificationDelivery.objects.filter(
        status=DeliveryStatus.PENDING, created_at__lt=timezone.now() - REDISPATCH_AFTER
    )
    abandoned = stale.filter(attempts__gte=MAX_ATTEMPTS).update(status=DeliveryStatus.FAILED)
    if abandoned:
        logger.error("notification_deliveries_failed", count=abandoned)

    waiting = list(stale.order_by("created_at").values_list("pk", flat=True)[:REDISPATCH_BATCH])
    for delivery_id in waiting:
        enqueue(send_notification_email, str(delivery_id))
    if waiting:
        logger.warning("notification_deliveries_redispatched", count=len(waiting))
    return len(waiting)


@shared_task(name="notifications.purge_old")
def purge_old() -> int:
    deleted, _ = Notification.objects.filter(read_at__lt=timezone.now() - KEEP_READ_FOR).delete()
    logger.info("notifications_purged", count=deleted)
    return deleted
