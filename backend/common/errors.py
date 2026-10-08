"""Domain exceptions and the single error envelope returned by every API endpoint.

Envelope::

    {"type", "title", "status", "code", "detail", "errors": {field: [messages]}, "request_id"}
"""

import math
from http import HTTPStatus
from typing import Any

import structlog
from django.conf import settings
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import set_rollback

from common import request_context

logger = structlog.get_logger(__name__)

FieldErrors = dict[str, list[str]]


class DomainError(exceptions.APIException):
    """Base for errors raised by services; ``code`` is the stable machine-readable identifier."""

    def __init__(
        self,
        detail: str | None = None,
        code: str | None = None,
        errors: FieldErrors | None = None,
    ) -> None:
        super().__init__(detail=detail, code=code)
        self.errors = errors or {}


class BadRequest(DomainError):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The request could not be processed."
    default_code = "bad_request"


class Conflict(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current state of the resource."
    default_code = "conflict"


class InvalidTransition(Conflict):
    default_detail = "This state transition is not allowed."
    default_code = "invalid_transition"


class StaleState(Conflict):
    default_detail = "The resource changed since it was last read."
    default_code = "stale_state"


class BusinessRuleViolation(DomainError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "The request violates a business rule."
    default_code = "business_rule_violation"


def _flatten(detail: Any, prefix: str = "") -> FieldErrors:
    if isinstance(detail, dict):
        flat: FieldErrors = {}
        for key, value in detail.items():
            flat.update(_flatten(value, f"{prefix}.{key}" if prefix else str(key)))
        return flat
    if isinstance(detail, list):
        flat = {}
        for index, item in enumerate(detail):
            if isinstance(item, (dict, list)):
                flat.update(_flatten(item, f"{prefix}.{index}" if prefix else str(index)))
            else:
                flat.setdefault(prefix or "non_field_errors", []).append(str(item))
        return flat
    return {prefix or "non_field_errors": [str(detail)]}


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    if not isinstance(exc, exceptions.APIException):
        if settings.DEBUG:
            return None  # let Django render the traceback page
        logger.exception("unhandled_exception", exc_info=exc)
        exc = exceptions.APIException()

    headers: dict[str, str] = {}
    auth_header = getattr(exc, "auth_header", None)
    if auth_header:
        headers["WWW-Authenticate"] = auth_header
    wait = getattr(exc, "wait", None)
    if wait:
        headers["Retry-After"] = str(math.ceil(wait))

    if isinstance(exc, exceptions.ValidationError):
        code = "validation_error"
        detail = "The request data is invalid."
        errors = _flatten(exc.detail)
    else:
        code = getattr(exc.detail, "code", None) or exc.default_code
        detail = str(exc.detail)
        errors = getattr(exc, "errors", {})

    set_rollback()
    return Response(
        {
            "type": f"urn:opportunity-network:error:{code}",
            "title": HTTPStatus(exc.status_code).phrase,
            "status": exc.status_code,
            "code": code,
            "detail": detail,
            "errors": errors,
            "request_id": request_context.get_request_id(),
        },
        status=exc.status_code,
        headers=headers,
    )


@extend_schema(exclude=True)
@api_view(["GET", "POST", "PUT", "PATCH", "DELETE"])
@permission_classes([AllowAny])
def api_not_found(request: Request) -> Response:
    raise exceptions.NotFound()
