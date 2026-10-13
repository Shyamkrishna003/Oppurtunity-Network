"""Every write to conversations and messages.

A message is saved first and announced afterwards. The row is the record: the push to an
open browser is only a hint that says "refetch", so one that is lost costs nothing.
"""

from functools import partial
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone

from common.errors import BusinessRuleViolation
from common.tasks import enqueue
from connections.selectors import are_connected
from messaging import selectors
from messaging.models import (
    MAX_BODY,
    PREVIEW_LENGTH,
    Conversation,
    ConversationParticipant,
    Message,
)
from realtime.tasks import publish_event
from users.models import User
from users.selectors import is_blocked_either_way


def _announce(user_id: UUID, event: str, data: dict[str, Any]) -> None:
    transaction.on_commit(partial(enqueue, publish_event, str(user_id), event, data))


def _create(user: User, other: User) -> Conversation | None:
    low, high = selectors.ordered(user.pk, other.pk)
    try:
        # A savepoint, so losing the race to the other person does not poison the transaction.
        with transaction.atomic():
            conversation = Conversation.objects.create(user_low_id=low, user_high_id=high)
            ConversationParticipant.objects.bulk_create(
                ConversationParticipant(conversation=conversation, user_id=user_id)
                for user_id in (low, high)
            )
            return conversation
    except IntegrityError:
        return None


def start(*, user: User, user_id: UUID) -> tuple[Conversation, bool]:
    """Open the conversation with someone, creating it if the two have never written.

    Returns the conversation and whether this call created it. A new one can only be
    started with a connection; one that already exists can always be reopened by either
    person (unless one has blocked the other, in which case neither can see it).
    """
    if user_id == user.pk:
        raise Http404
    # Not there, deactivated and blocked either way all look the same: not found. Whether
    # the person's profile is private does not matter here: being connected is what counts.
    other = User.objects.filter(pk=user_id, is_active=True).first()
    if other is None or is_blocked_either_way(user, other):
        raise Http404
    pair = selectors.between(user.pk, other.pk)
    created = False
    if not pair.exists():
        if not are_connected(user, other):
            message = "You can only start a conversation with one of your connections."
            raise BusinessRuleViolation(message, code="not_connected")
        with transaction.atomic():
            # None means the other person created it in this same instant, which is fine.
            created = _create(user, other) is not None
    return selectors.get_conversation(user, pair.get().pk), created


def send(*, user: User, conversation_id: UUID, body: str, client_id: UUID) -> tuple[Message, bool]:
    """Send a message. Returns it and whether this call created it.

    Sending the same ``client_id`` again does not send twice: the first message is
    returned, whatever the second body said. That makes a retry after a timeout safe.
    """
    body = body.strip()
    if not body or len(body) > MAX_BODY:
        problem = f"Write a message of at most {MAX_BODY} characters."
        raise BusinessRuleViolation(problem, code="invalid_message", errors={"body": [problem]})

    with transaction.atomic():
        # Locking the conversation puts its messages in one order and keeps the preview
        # in step with the newest of them.
        conversation = (
            selectors.visible_to(user).select_for_update(of=("self",)).filter(pk=conversation_id)
        ).first()
        if conversation is None:
            raise Http404
        existing = Message.objects.filter(
            conversation=conversation, sender=user, client_id=client_id
        ).first()
        if existing is not None:
            return existing, False
        other_id = conversation.other_id(user.pk)
        if not User.objects.filter(pk=other_id, is_active=True).exists():
            raise BusinessRuleViolation(
                "This person can no longer receive messages.", code="recipient_unavailable"
            )

        now = timezone.now()
        message = Message.objects.create(
            conversation=conversation, sender=user, body=body, client_id=client_id, created_at=now
        )
        conversation.last_message_at = now
        conversation.last_message_preview = body[:PREVIEW_LENGTH]
        conversation.save(update_fields=["last_message_at", "last_message_preview", "updated_at"])
        # Having written it, the sender has read up to it.
        ConversationParticipant.objects.filter(conversation=conversation, user=user).update(
            last_read_at=now
        )
        data = {"conversation_id": str(conversation.pk), "message_id": str(message.pk)}
        _announce(other_id, "message.created", data)
        # The sender's other tabs and devices, too.
        _announce(user.pk, "message.created", data)
        return message, True


def mark_read(*, user: User, conversation_id: UUID, up_to_message_id: UUID) -> bool:
    """Record that the user has read the conversation up to a message. Returns whether
    that moved their position: it only ever moves forward, so reading an older message
    after a newer one changes nothing."""
    conversation = selectors.visible_to(user).filter(pk=conversation_id).first()
    if conversation is None:
        raise Http404
    read_at = (
        Message.objects.filter(pk=up_to_message_id, conversation=conversation)
        .values_list("created_at", flat=True)
        .first()
    )
    if read_at is None:
        raise Http404
    with transaction.atomic():
        position = ConversationParticipant.objects.filter(conversation=conversation, user=user)
        moved = position.filter(last_read_at__isnull=True).update(
            last_read_at=read_at
        ) or position.filter(last_read_at__lt=read_at).update(last_read_at=read_at)
        if moved:
            data = {"conversation_id": str(conversation.pk)}
            # The reader's other tabs clear their badge; the other person sees "seen".
            _announce(user.pk, "conversation.read", data)
            _announce(conversation.other_id(user.pk), "conversation.read", data)
    return bool(moved)
