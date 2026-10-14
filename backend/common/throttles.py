from typing import TYPE_CHECKING

from rest_framework.request import Request
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

from common import request_context

if TYPE_CHECKING:
    # DRF loads the default throttle while it is still defining its views.
    from rest_framework.views import APIView


class ApiThrottle(SimpleRateThrottle):
    """The limit every endpoint has unless it sets its own: generous for a person using the
    app, tight enough to stop a script walking through everything. Counted per account, or
    per address for a visitor."""

    def __init__(self) -> None:
        # The rate depends on who is asking, so it is looked up per request.
        pass

    def allow_request(self, request: Request, view: APIView) -> bool:
        signed_in = bool(request.user and request.user.is_authenticated)
        self.scope = "api_user" if signed_in else "api_anon"
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)

    def get_cache_key(self, request: Request, view: APIView) -> str:
        if request.user and request.user.is_authenticated:
            ident = str(request.user.pk)
        else:
            ident = request_context.get_client_ip() or self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ScopedThrottle(ScopedRateThrottle):
    """Per-view rate limit (``throttle_scope``), keyed by user or, for anonymous callers, by IP.

    The app sits behind our reverse proxy, so the peer address is the proxy; the real
    client address comes from the request context.
    """

    def get_ident(self, request: Request) -> str:
        return request_context.get_client_ip() or super().get_ident(request)
