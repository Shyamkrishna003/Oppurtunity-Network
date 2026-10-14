from django.core.exceptions import ImproperlyConfigured

from config.logging import build_logging

from .base import *  # noqa: F403
from .base import (
    ALLOWED_HOSTS,
    FRONTEND_URL,
    REFRESH_COOKIE_SECURE,
    SECRET_KEY,
    TRUST_PROXY_HEADERS,
)
from .guards import production_problems

# Refuse to start rather than run with development values.
_problems = production_problems(
    secret_key=SECRET_KEY,
    allowed_hosts=ALLOWED_HOSTS,
    frontend_url=FRONTEND_URL,
    refresh_cookie_secure=REFRESH_COOKIE_SECURE,
    trust_proxy_headers=TRUST_PROXY_HEADERS,
)
if _problems:
    raise ImproperlyConfigured("Unsafe production configuration: " + " ".join(_problems))

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^healthz$", r"^readyz$"]
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

LOGGING = build_logging(json_logs=True, level="INFO")
