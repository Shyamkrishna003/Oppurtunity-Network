import re
import time
import uuid
from collections.abc import Callable

import structlog
from django.conf import settings
from django.http import HttpRequest, HttpResponse

from common import request_context

logger = structlog.get_logger("request")

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_UNLOGGED_PATHS = frozenset({"/healthz", "/readyz"})


def _client_ip(request: HttpRequest) -> str | None:
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("X-Real-IP")
        if forwarded:
            return forwarded.strip()
    return request.META.get("REMOTE_ADDR")


class RequestContextMiddleware:
    """Assigns a request ID, exposes it to logs/services, and logs one line per request."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        # A client-supplied ID is only accepted in a safe shape, since it is written to logs.
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request_context.bind(request_id=request_id, client_ip=_client_ip(request))

        started = time.perf_counter()
        try:
            response = self.get_response(request)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)

        response[REQUEST_ID_HEADER] = request_id
        if request.path not in _UNLOGGED_PATHS:
            user = getattr(request, "user", None)
            logger.info(
                "request_finished",
                method=request.method,
                path=request.path,
                status=response.status_code,
                duration_ms=duration_ms,
                user_id=str(user.pk) if user is not None and user.is_authenticated else None,
            )
        request_context.clear()
        return response
