from uuid import UUID

from django.conf import settings
from django.db import models
from django.db.models.functions import Length, Trim
from django.db.models.lookups import GreaterThanOrEqual, LessThanOrEqual
from django.utils import timezone

from common.models import TimestampedModel, UUIDModel

MAX_BODY = 4000
PREVIEW_LENGTH = 140


class Conversation(TimestampedModel):
    """A private thread between two people.

    There is one per pair, whoever wrote first: the two users are stored in a fixed order
    (``user_low`` has the smaller ID), so both starting a conversation at the same moment
    meet on the same unique constraint instead of creating two threads.
    """

    user_low = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    user_high = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    # When the conversation last had something happen in it: its creation, then each
    # message. The inbox is ordered by this.
    last_message_at = models.DateTimeField(default=timezone.now)
    # The start of the latest message, so the inbox needs no second query per row.
    last_message_preview = models.CharField(max_length=PREVIEW_LENGTH, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user_low", "user_high"], name="messaging_conversation_pair_unique"
            ),
            # Also rules out a conversation with oneself.
            models.CheckConstraint(
                condition=models.Q(user_low__lt=models.F("user_high")),
                name="messaging_conversation_pair_ordered",
            ),
        ]
        indexes = [
            # The inbox looks a user up on either side, most recent first.
            models.Index(fields=["user_low", "-last_message_at"], name="messaging_inbox_low"),
            models.Index(fields=["user_high", "-last_message_at"], name="messaging_inbox_high"),
        ]

    def __str__(self) -> str:
        return f"{self.user_low_id} - {self.user_high_id}"

    def other_id(self, user_id: UUID) -> UUID:
        """The ID of the person on the other side from ``user_id``."""
        return self.user_high_id if self.user_low_id == user_id else self.user_low_id


class ConversationParticipant(UUIDModel):
    """One person's own view of a conversation: how far they have read.

    A separate table (rather than two columns on the conversation) so that group
    conversations, if they ever come, need no remodelling.
    """

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="participants"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    # Everything up to and including this moment has been read. Only ever moves forward.
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "user"], name="messaging_participant_unique"
            ),
        ]
        indexes = [models.Index(fields=["user"], name="messaging_participant_user")]

    def __str__(self) -> str:
        return f"{self.user_id} in {self.conversation_id}"


class Message(UUIDModel):
    """One message. Never edited or deleted.

    ``client_id`` is chosen by the sender's device for each message it composes. Sending
    the same one again (a retry after a timeout) finds the first message instead of
    creating a second.
    """

    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name="messages"
    )
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    body = models.TextField(max_length=MAX_BODY)
    client_id = models.UUIDField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "sender", "client_id"], name="messaging_message_once"
            ),
            # Not empty, counting a message of only blank space as empty, and not too long.
            models.CheckConstraint(
                condition=models.Q(GreaterThanOrEqual(Length(Trim("body")), 1))
                & models.Q(LessThanOrEqual(Length("body"), MAX_BODY)),
                name="messaging_message_body_length",
            ),
        ]
        indexes = [
            # A thread in order, and "what arrived after I last read".
            models.Index(fields=["conversation", "created_at", "id"], name="messaging_thread"),
        ]

    def __str__(self) -> str:
        return f"{self.sender_id} in {self.conversation_id}"
