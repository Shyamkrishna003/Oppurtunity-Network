"""Per-request (or per-task) context available to services without passing ``request`` around."""

from contextvars import ContextVar

import structlog

_request_id: ContextVar[str] = ContextVar("request_id", default="")
_client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)


def bind(*, request_id: str, client_ip: str | None = None) -> None:
    _request_id.set(request_id)
    _client_ip.set(client_ip)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)


def clear() -> None:
    _request_id.set("")
    _client_ip.set(None)
    structlog.contextvars.clear_contextvars()


def get_request_id() -> str:
    return _request_id.get()


def get_client_ip() -> str | None:
    return _client_ip.get()
