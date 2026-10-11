from django.conf import settings
from django.db import models

from common.models import UUIDModel


class NotificationType(models.TextChoices):
    ORGANIZATION_INVITATION = "ORGANIZATION_INVITATION", "Invited to an organization"
    ORGANIZATION_ROLE_CHANGED = "ORGANIZATION_ROLE_CHANGED", "Role changed in an organization"
    ORGANIZATION_REMOVED = "ORGANIZATION_REMOVED", "Removed from an organization"
    COMMUNITY_INVITATION = "COMMUNITY_INVITATION", "Invited to a community"
    COMMUNITY_JOIN_REQUESTED = "COMMUNITY_JOIN_REQUESTED", "Someone asked to join"
    COMMUNITY_JOIN_APPROVED = "COMMUNITY_JOIN_APPROVED", "Request to join approved"
    COMMUNITY_JOIN_REJECTED = "COMMUNITY_JOIN_REJECTED", "Request to join declined"
    COMMUNITY_REMOVED = "COMMUNITY_REMOVED", "Removed from a community"
    SHARE_SUBMITTED = "SHARE_SUBMITTED", "Opportunity waiting for review"
    SHARE_APPROVED = "SHARE_APPROVED", "Opportunity approved by a community"
    SHARE_REJECTED = "SHARE_REJECTED", "Opportunity declined by a community"
    SHARE_REMOVED = "SHARE_REMOVED", "Opportunity removed by a community"
    OPPORTUNITY_EXPIRED = "OPPORTUNITY_EXPIRED", "Opportunity expired"
    APPLICATION_RECEIVED = "APPLICATION_RECEIVED", "Someone applied to a job"
    APPLICATION_WITHDRAWN = "APPLICATION_WITHDRAWN", "An application was withdrawn"
    APPLICATION_ADVANCED = "APPLICATION_ADVANCED", "Your application moved forward"
    APPLICATION_REJECTED = "APPLICATION_REJECTED", "Your application was not selected"


class Category(models.TextChoices):
    """What a person can switch on or off. Several notification types share a category, so
    the preferences screen stays short as types are added."""

    INVITATIONS = "INVITATIONS", "Invitations"
    MEMBERSHIP = "MEMBERSHIP", "My memberships"
    REVIEW = "REVIEW", "Things waiting for my review"
    POSTINGS = "POSTINGS", "My opportunities"
    APPLICATIONS = "APPLICATIONS", "My applications"


class Channel(models.TextChoices):
    EMAIL = "EMAIL", "Email"


class DeliveryStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SENT = "SENT", "Sent"
    FAILED = "FAILED", "Failed"
    SKIPPED = "SKIPPED", "Skipped"


class Notification(UUIDModel):
    """Something that happened which one person should know about.

    This row is the durable record. Pushing it to an open browser and emailing it are both
    derived from it and can be repeated or lost without losing the notification.

    The target is a loose ``(target_type, target_id)`` reference, so a notification survives
    the deletion of what it is about. ``payload`` holds only what is needed to word the
    notification later (names and titles as they were), never anything the recipient could
    not otherwise see.
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=32, choices=NotificationType.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    target_type = models.CharField(max_length=64)
    target_id = models.UUIDField()
    payload = models.JSONField(default=dict, blank=True)
    # Set when the same event must not notify the same person twice (a sweep that may rerun).
    # NULL rather than "" for "no key": the unique constraint below must ignore those rows.
    dedupe_key = models.CharField(max_length=120, null=True, blank=True)  # noqa: DJ001
    # False when the person turned the in-app channel off for this category but still gets
    # the email: the row exists for the delivery, but is not shown in their list.
    in_app = models.BooleanField(default=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "dedupe_key"],
                condition=models.Q(dedupe_key__isnull=False),
                name="notifications_dedupe_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(type__in=NotificationType.values),
                name="notifications_type_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["recipient", "-created_at"], name="notifications_recent"),
            # The unread badge.
            models.Index(
                fields=["recipient"],
                condition=models.Q(read_at__isnull=True, in_app=True),
                name="notifications_unread",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.type} for {self.recipient_id}"


class NotificationDelivery(UUIDModel):
    """One attempt-tracked delivery of a notification over a channel other than the app."""

    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="deliveries"
    )
    channel = models.CharField(max_length=8, choices=Channel.choices)
    status = models.CharField(
        max_length=8, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "notification deliveries"
        constraints = [
            models.UniqueConstraint(
                fields=["notification", "channel"], name="notifications_delivery_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=DeliveryStatus.values),
                name="notifications_delivery_status_valid",
            ),
        ]
        indexes = [
            # The redispatch sweep: deliveries still waiting, oldest first.
            models.Index(
                fields=["created_at"],
                condition=models.Q(status=DeliveryStatus.PENDING),
                name="notifications_delivery_pending",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.channel} delivery of {self.notification_id} ({self.status})"


class NotificationPreference(models.Model):
    """A person's choice for one category. No row means the defaults apply."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preferences"
    )
    category = models.CharField(max_length=16, choices=Category.choices)
    in_app = models.BooleanField()
    email = models.BooleanField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "category"], name="notifications_preference_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(category__in=Category.values),
                name="notifications_preference_category_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.category}"
