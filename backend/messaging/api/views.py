from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from common.pagination import CursorPagination
from common.throttles import ScopedThrottle
from messaging import selectors, services
from messaging.api import serializers
from messaging.models import Conversation, Message
from users.api.utils import current_user
from users.permissions import IsVerified


class _MostRecentFirst(CursorPagination):
    ordering = ("-last_message_at", "-id")


class ConversationListView(generics.ListAPIView[Conversation]):
    """``GET`` is the caller's inbox, most recent first. ``POST`` opens the conversation
    with someone, creating it if there is none yet."""

    serializer_class = serializers.ConversationSerializer
    pagination_class = _MostRecentFirst

    def get_permissions(self) -> list[BasePermission]:
        return [IsVerified()] if self.request.method == "POST" else [IsAuthenticated()]

    def get_throttles(self) -> list[BaseThrottle]:
        if self.request.method != "POST":
            return []
        self.throttle_scope = "conversation_start"
        return [ScopedThrottle()]

    def get_queryset(self) -> QuerySet[Conversation]:
        if getattr(self, "swagger_fake_view", False):
            return Conversation.objects.none()
        return selectors.inbox(current_user(self.request))

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "viewer": self.request.user}

    @extend_schema(
        request=serializers.StartConversationSerializer,
        responses={
            201: serializers.ConversationSerializer,
            200: serializers.ConversationSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        """Open the conversation with ``user_id``. 201 if it was created, 200 if it already
        existed. A new one needs the two to be connected (422 ``not_connected``); someone
        who does not exist, or with a block either way, is 404."""
        serializer = serializers.StartConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation, created = services.start(
            user=current_user(request), user_id=serializer.validated_data["user_id"]
        )
        data = serializers.ConversationSerializer(
            conversation, context={"viewer": request.user}
        ).data
        return Response(data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class ConversationDetailView(APIView):
    @extend_schema(responses=serializers.ConversationSerializer)
    def get(self, request: Request, conversation_id: UUID) -> Response:
        conversation = selectors.get_conversation(current_user(request), conversation_id)
        return Response(
            serializers.ConversationSerializer(conversation, context={"viewer": request.user}).data
        )


class UnreadCountView(APIView):
    @extend_schema(responses=serializers.UnreadSerializer)
    def get(self, request: Request) -> Response:
        """How many conversations have messages the caller has not read."""
        return Response({"count": selectors.unread_conversations(current_user(request))})


class MessageListView(generics.ListAPIView[Message]):
    """``GET`` pages back through a conversation, newest first. ``POST`` sends a message."""

    serializer_class = serializers.MessageSerializer

    def get_permissions(self) -> list[BasePermission]:
        return [IsVerified()] if self.request.method == "POST" else [IsAuthenticated()]

    def get_throttles(self) -> list[BaseThrottle]:
        if self.request.method != "POST":
            return []
        self.throttle_scope = "message_send"
        return [ScopedThrottle()]

    def get_queryset(self) -> QuerySet[Message]:
        if getattr(self, "swagger_fake_view", False):
            return Message.objects.none()
        conversation = selectors.get_conversation(
            current_user(self.request), self.kwargs["conversation_id"]
        )
        return selectors.messages_of(conversation)

    @extend_schema(
        request=serializers.SendMessageSerializer,
        responses={201: serializers.MessageSerializer, 200: serializers.MessageSerializer},
    )
    def post(self, request: Request, conversation_id: UUID) -> Response:
        """Send a message. 201 when it was sent; 200 with the original message when this
        ``client_id`` was already used in the conversation, so a retry never sends twice."""
        serializer = serializers.SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message, created = services.send(
            user=current_user(request),
            conversation_id=conversation_id,
            body=serializer.validated_data["body"],
            client_id=serializer.validated_data["client_id"],
        )
        return Response(
            serializers.MessageSerializer(message).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class MarkReadView(APIView):
    @extend_schema(request=serializers.MarkReadSerializer, responses={204: None})
    def post(self, request: Request, conversation_id: UUID) -> Response:
        """Say the caller has read the conversation up to a message. The position only
        moves forward, so doing this again, or with an older message, changes nothing."""
        serializer = serializers.MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.mark_read(
            user=current_user(request),
            conversation_id=conversation_id,
            up_to_message_id=serializer.validated_data["up_to_message_id"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
