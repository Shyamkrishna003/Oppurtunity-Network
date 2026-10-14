from django.core.exceptions import ImproperlyConfigured

from config.logging import build_logging

from .base import *  # noqa: F403
from .base import (
    ALLOWED_HOSTS,
    DATABASES,
    FRONTEND_URL,
    REFRESH_COOKIE_SECURE,
    SECRET_KEY,
    SENTRY_DSN,
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

# A fixed number of database connections per process, shared by its requests. Without a
# pool every request being served at the same moment opens its own, and a burst of visitors
# asks for more than PostgreSQL allows: the excess fail instead of waiting. With one, they
# queue for up to ``timeout`` seconds. Keep (processes x max_size) below the database's
# max_connections (100 by default).
DATABASES["default"]["CONN_MAX_AGE"] = 0
DATABASES["default"]["OPTIONS"]["pool"] = {
    "min_size": 1,
    "max_size": env.int("DB_POOL_MAX_SIZE", default=20),  # noqa: F405
    "timeout": 20,
}

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

if SENTRY_DSN:
    import sentry_sdk

    # Django and Celery are picked up by themselves. Errors only: no performance traces,
    # and nothing that identifies a person (no addresses, cookies or request bodies).
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=False,
        traces_sample_rate=0.0,
        release=env("APP_VERSION", default=None),  # noqa: F405
    )
