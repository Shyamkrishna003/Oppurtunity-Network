from uuid import UUID

from django.conf import settings
from django.db import models

from common.models import TimestampedModel


class ConnectionStatus(models.TextChoices):
    REQUESTED = "REQUESTED", "Requested"
    ACCEPTED = "ACCEPTED", "Accepted"
    DECLINED = "DECLINED", "Declined"


class Connection(TimestampedModel):
    """The relationship between two people: asked for, accepted, or declined.

    There is one row per pair, whoever asked: the two users are stored in a fixed order
    (``user_low`` has the smaller ID), so "A asked B" and "B asked A" at the same moment
    meet on the same unique constraint instead of creating two rows.

    A block is not a state here. It lives in ``users.UserBlock``, which needs no prior
    connection and has a direction; blocking deletes the pair's row.
    """

    user_low = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    user_high = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    status = models.CharField(
        max_length=9, choices=ConnectionStatus.choices, default=ConnectionStatus.REQUESTED
    )
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user_low", "user_high"], name="connections_pair_unique"
            ),
            # Also rules out a connection with oneself.
            models.CheckConstraint(
                condition=models.Q(user_low__lt=models.F("user_high")),
                name="connections_pair_ordered",
            ),
            models.CheckConstraint(
                condition=models.Q(requested_by=models.F("user_low"))
                | models.Q(requested_by=models.F("user_high")),
                name="connections_requested_by_one_of_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=ConnectionStatus.values),
                name="connections_status_valid",
            ),
        ]
        indexes = [
            # "My connections" and "requests waiting for me" look a user up on either side.
            models.Index(fields=["user_low", "status"], name="connections_low_status"),
            models.Index(fields=["user_high", "status"], name="connections_high_status"),
        ]

    def __str__(self) -> str:
        return f"{self.user_low_id} - {self.user_high_id} ({self.status})"

    def other_id(self, user_id: UUID) -> UUID:
        """The ID of the person on the other side from ``user_id``."""
        return self.user_high_id if self.user_low_id == user_id else self.user_low_id
