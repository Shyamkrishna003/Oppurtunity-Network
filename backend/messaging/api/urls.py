from django.urls import path

from messaging.api import views

urlpatterns = [
    path("conversations/", views.ConversationListView.as_view(), name="conversation-list"),
    # Before the ":id" route, which would otherwise try to read "unread-count" as an ID.
    path(
        "conversations/unread-count/",
        views.UnreadCountView.as_view(),
        name="conversation-unread-count",
    ),
    path(
        "conversations/<uuid:conversation_id>/",
        views.ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
    path(
        "conversations/<uuid:conversation_id>/messages/",
        views.MessageListView.as_view(),
        name="conversation-messages",
    ),
    path(
        "conversations/<uuid:conversation_id>/read/",
        views.MarkReadView.as_view(),
        name="conversation-read",
    ),
]
