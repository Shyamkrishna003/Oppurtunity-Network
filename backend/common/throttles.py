from rest_framework.request import Request
from rest_framework.throttling import ScopedRateThrottle

from common import request_context


class ScopedThrottle(ScopedRateThrottle):
    """Per-view rate limit (``throttle_scope``), keyed by user or, for anonymous callers, by IP.

    The app sits behind our reverse proxy, so the peer address is the proxy; the real
    client address comes from the request context.
    """

    def get_ident(self, request: Request) -> str:
        return request_context.get_client_ip() or super().get_ident(request)
