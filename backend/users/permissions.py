from urllib.parse import urlsplit

from django.conf import settings
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


class IsVerified(BasePermission):
    """Authenticated and has confirmed their email address."""

    message = "Verify your email address to do this."
    code = "email_not_verified"

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_email_verified)


class SameOriginRequest(BasePermission):
    """CSRF defence for the endpoints authenticated by the refresh cookie.

    The cookie is ``SameSite=Strict``; in addition the browser-set ``Origin`` must be ours and
    the request must carry a custom header, which a cross-site form or simple request cannot.
    """

    message = "This request must come from the application."
    code = "cross_origin_denied"

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not request.headers.get("X-Requested-With"):
            return False
        origin = request.headers.get("Origin")
        if not origin:
            return False
        if origin in settings.CSRF_TRUSTED_ORIGINS:
            return True
        return urlsplit(origin).netloc == request.get_host()
