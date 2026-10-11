from typing import Any

from django.urls import path

from realtime.consumers import StreamConsumer

# One socket carries everything pushed to a user; there are no per-resource sockets.
websocket_urlpatterns: list[Any] = [
    path("ws/stream/", StreamConsumer.as_asgi()),
]
