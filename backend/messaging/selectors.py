"""Read queries for messaging. Views load objects only through these.

Every query starts from one person and returns only conversations they are part of. A pair
where either has blocked the other has no conversation as far as either can tell: it is
left out of every list and cannot be opened, and comes back if the block is lifted.
"""

from datetime import UTC, datetime
from uuid import UUID

from django.db.models import (
    Count,
    DateTimeField,
    Exists,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import Http404

from messaging.models import Conversation, ConversationParticipant, Message
from users.models import User, UserBlock

# Stands in for "never" where a reading position is compared against.
_LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


def ordered(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    """The pair in the order it is stored: smaller ID first."""
    return (first, second) if first < second else (second, first)


def between(first: UUID, second: UUID) -> QuerySet[Conversation]:
    """The pair's conversation: at most one."""
    low, high = ordered(first, second)
    return Conversation.objects.filter(user_low_id=low, user_high_id=high)


def visible_to(user: User) -> QuerySet[Conversation]:
    """The conversations the user is in, leaving out any with someone blocked either way."""
    blocked = UserBlock.objects.filter(
        Q(blocker=OuterRef("user_low"), blocked=OuterRef("user_high"))
        | Q(blocker=OuterRef("user_high"), blocked=OuterRef("user_low"))
    )
    return Conversation.objects.filter(Q(user_low=user) | Q(user_high=user)).exclude(
        Exists(blocked)
    )


def _with_state(conversations: QuerySet[Conversation], user: User) -> QuerySet[Conversation]:
    """Everything a serialized conversation needs: both people, how many messages the user
    has not read, and how far the other person has read."""
    mine = ConversationParticipant.objects.filter(conversation=OuterRef("pk"), user=user)
    theirs = ConversationParticipant.objects.filter(conversation=OuterRef("pk")).exclude(user=user)
    # Messages from the other person that arrived after the user's reading position
    # (all of them, if the user has never read the conversation).
    unread = (
        Message.objects.filter(
            conversation=OuterRef("pk"),
            created_at__gt=Coalesce(
                OuterRef("my_read_at"), Value(_LONG_AGO), output_field=DateTimeField()
            ),
        )
        .exclude(sender=user)
        .order_by()
        .values("conversation")
        .annotate(total=Count("pk"))
        .values("total")
    )
    return (
        conversations.select_related("user_low__profile", "user_high__profile")
        .annotate(
            my_read_at=Subquery(mine.values("last_read_at")[:1]),
            other_read_at=Subquery(theirs.values("last_read_at")[:1]),
        )
        .annotate(unread_count=Coalesce(Subquery(unread[:1]), 0))
    )


def inbox(user: User) -> QuerySet[Conversation]:
    """The user's conversations, for listing. The view orders them, most recent first."""
    return _with_state(visible_to(user), user)


def get_conversation(user: User, conversation_id: UUID) -> Conversation:
    """The conversation if the user is in it, else 404: one they are not part of, one with
    someone blocked and one that does not exist look the same."""
    conversation = _with_state(visible_to(user).filter(pk=conversation_id), user).first()
    if conversation is None:
        raise Http404
    return conversation


def messages_of(conversation: Conversation) -> QuerySet[Message]:
    """A conversation's messages, for its participants. The caller has established that the
    reader is one."""
    return Message.objects.filter(conversation=conversation)


def unread_conversations(user: User) -> int:
    """How many conversations have something the user has not read: the number on the badge."""
    # ``unread_count`` is the annotation added by ``_with_state``.
    return inbox(user).filter(unread_count__gt=0).count()  # type: ignore[misc]
