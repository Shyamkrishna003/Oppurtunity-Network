from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = "notifications"

    def ready(self) -> None:
        from common import metrics
        from notifications.models import DeliveryStatus, NotificationDelivery

        def waiting() -> float:
            return float(NotificationDelivery.objects.filter(status=DeliveryStatus.PENDING).count())

        # Stays near zero when email is flowing; a number that keeps growing means the
        # worker or the mail provider is down.
        metrics.gauge(
            "notification_emails_pending", "Notification emails waiting to be sent.", waiting
        )
