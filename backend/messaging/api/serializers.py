from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from messaging.models import MAX_BODY, Conversation, Message
from organizations.api.serializers import PersonSerializer
from users.models import User


class ConversationSerializer(serializers.ModelSerializer[Conversation]):
    """A conversation as one of its two people sees it. Pass ``viewer`` in the context."""

    other = serializers.SerializerMethodField()
    unread_count = serializers.IntegerField(read_only=True)
    # How far the other person has read, for showing "seen" under one's own messages.
    other_read_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        model = Conversation
        fields = (
            "id",
            "other",
            "last_message_at",
            "last_message_preview",
            "unread_count",
            "other_read_at",
            "created_at",
        )

    @extend_schema_field(PersonSerializer)
    def get_other(self, conversation: Conversation) -> Any:
        viewer: User = self.context["viewer"]
        other = (
            conversation.user_high
            if conversation.user_low_id == viewer.pk
            else conversation.user_low
        )
        return PersonSerializer(other).data


class StartConversationSerializer(serializers.Serializer[Any]):
    user_id = serializers.UUIDField()


class MessageSerializer(serializers.ModelSerializer[Message]):
    class Meta:
        model = Message
        fields = ("id", "conversation_id", "sender_id", "body", "client_id", "created_at")


class SendMessageSerializer(serializers.Serializer[Any]):
    body = serializers.CharField(max_length=MAX_BODY, trim_whitespace=True)
    # Chosen by the sender's device for each message it composes; repeating one is a retry.
    client_id = serializers.UUIDField()


class MarkReadSerializer(serializers.Serializer[Any]):
    up_to_message_id = serializers.UUIDField()


class UnreadSerializer(serializers.Serializer[Any]):
    count = serializers.IntegerField()
