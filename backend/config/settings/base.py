from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS: list[str] = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# True only when the app is reachable exclusively through our own reverse proxy,
# which overwrites X-Real-IP with the peer address.
TRUST_PROXY_HEADERS = env.bool("TRUST_PROXY_HEADERS", default=False)

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "drf_spectacular",
    "channels",
    "common",
    "users",
    "taxonomy",
    "organizations",
    "communities",
    "opportunities",
    "jobs",
    "events",
    "applications",
    "connections",
    "referrals",
    "notifications",
    "realtime",
    "audit",
]

MIDDLEWARE = [
    "common.middleware.RequestContextMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "users.User"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded files go through Django's storage API; swap STORAGES["default"] for an
# S3-compatible backend in production without touching application code.
MEDIA_URL = "/media/"
MEDIA_ROOT = env.path("MEDIA_ROOT", default=str(BASE_DIR / "media"))
AVATAR_MAX_BYTES = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
# Files that need a permission check (resumes) are kept outside MEDIA_ROOT and are only
# served through signed links that expire quickly. See common.storage.
PRIVATE_MEDIA_ROOT = env.path("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private_media"))
PRIVATE_DOWNLOAD_TTL = timedelta(seconds=60)
RESUME_MAX_BYTES = 5 * 1024 * 1024

# Origin of the web app, used to build links in emails.
FRONTEND_URL = env("FRONTEND_URL").rstrip("/")

# Sessions: a short-lived access token held in memory by the SPA, and a rotating refresh
# token in an HttpOnly cookie that is only ever sent to the auth endpoints.
ACCESS_TOKEN_LIFETIME = timedelta(minutes=10)
REFRESH_TOKEN_LIFETIME = timedelta(days=14)
# Two tabs can refresh at once; the just-rotated token stays usable this long before its
# reuse is treated as theft.
REFRESH_TOKEN_REUSE_GRACE = timedelta(seconds=10)
REFRESH_COOKIE_NAME = "on_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth/"
REFRESH_COOKIE_SECURE = env.bool("AUTH_COOKIE_SECURE", default=True)
EMAIL_VERIFICATION_MAX_AGE = timedelta(days=3)
PASSWORD_RESET_TIMEOUT = 60 * 60
LOGIN_FAILURE_LIMIT = 10
LOGIN_FAILURE_WINDOW = timedelta(minutes=15)

ORGANIZATION_INVITATION_LIFETIME = timedelta(days=7)
# How long a referral request waits for an answer before it expires.
REFERRAL_REQUEST_LIFETIME = timedelta(days=14)

# WebSocket. A ticket is fetched over the API and presented once, within seconds.
WS_TICKET_TTL = timedelta(seconds=30)
# How often the client is told to send a heartbeat, and how long silence is tolerated.
WS_HEARTBEAT = timedelta(seconds=30)
WS_IDLE_TIMEOUT = timedelta(seconds=75)
# A socket is closed after this long so the client must prove again, by getting a new
# ticket, that its session is still valid.
WS_SESSION_MAX_AGE = timedelta(minutes=60)

# Redis: separate logical databases for cache, Celery broker, and the channel layer.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_CACHE_URL"),
    },
}
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.pubsub.RedisPubSubChannelLayer",
        "CONFIG": {"hosts": [env("CHANNEL_REDIS_URL")]},
    },
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SOFT_TIME_LIMIT = 60
CELERY_TASK_TIME_LIMIT = 90
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_BEAT_SCHEDULE = {
    "expire-opportunities": {
        "task": "opportunities.expire_due",
        "schedule": timedelta(minutes=5),
        "options": {"queue": "scheduled"},
    },
    "advance-event-states": {
        "task": "events.advance_states",
        "schedule": timedelta(minutes=1),
        "options": {"queue": "scheduled"},
    },
    "sweep-referrals": {
        "task": "referrals.sweep",
        "schedule": timedelta(minutes=10),
        "options": {"queue": "scheduled"},
    },
    "redispatch-notification-deliveries": {
        "task": "notifications.redispatch_pending",
        "schedule": timedelta(minutes=5),
        "options": {"queue": "scheduled"},
    },
    "purge-old-notifications": {
        "task": "notifications.purge_old",
        "schedule": timedelta(hours=24),
        "options": {"queue": "scheduled"},
    },
    "purge-expired-refresh-tokens": {
        "task": "users.purge_expired_refresh_tokens",
        "schedule": timedelta(hours=24),
        "options": {"queue": "scheduled"},
    },
}

EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@opportunity-network.local")

REST_FRAMEWORK = {
    # Deny by default: every endpoint must opt in to weaker permissions explicitly.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["users.authentication.AccessTokenAuthentication"],
    "DEFAULT_THROTTLE_RATES": {
        "auth_login": "20/min",
        "auth_register": "10/hour",
        "auth_email": "10/hour",
        "auth_refresh": "60/min",
        "auth_password": "10/hour",
        "upload": "30/hour",
        "skill_create": "30/day",
        "user_block": "60/hour",
        "organization_create": "5/day",
        "organization_invite": "30/hour",
        "community_create": "5/day",
        "community_invite": "60/hour",
        "community_join": "60/hour",
        "opportunity_create": "30/day",
        "opportunity_share": "60/hour",
        "opportunity_search": "120/min",
        "application_create": "30/day",
        "event_register": "60/hour",
        "connection_request": "50/day",
        "referral_request": "20/day",
        "ws_ticket": "30/min",
    },
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "common.pagination.CursorPagination",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "common.errors.exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Opportunity Network API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Several models have a field called "status" or "role"; name each enum after its model.
    "ENUM_NAME_OVERRIDES": {
        "OrganizationRoleEnum": "organizations.models.OrganizationRole",
        # Organizations and communities share one set of values: active or suspended.
        "TenantStatusEnum": "organizations.models.OrganizationStatus",
        "InvitationStatusEnum": "organizations.models.InvitationStatus",
        "CommunityRoleEnum": "communities.models.CommunityRole",
        "OpportunityTypeEnum": "opportunities.models.OpportunityType",
        "NotificationTypeEnum": "notifications.models.NotificationType",
        "NotificationCategoryEnum": "notifications.models.Category",
        "OpportunityStatusEnum": "opportunities.models.OpportunityStatus",
        "ApplicationStatusEnum": "applications.models.ApplicationStatus",
        "ReferralStatusEnum": "referrals.models.ReferralStatus",
        "RegistrationStatusEnum": "events.models.RegistrationStatus",
        "OpportunityVisibilityEnum": "opportunities.models.OpportunityVisibility",
        "CloseReasonEnum": "opportunities.models.CloseReason",
        "ShareStatusEnum": "opportunities.models.DistributionStatus",
        "WorkModeEnum": "common.choices.WorkMode",
        "ExperienceLevelEnum": "common.choices.ExperienceLevel",
        "CommunityMemberStatusEnum": "communities.models.MemberStatus",
        "CommunityVisibilityEnum": "communities.models.CommunityVisibility",
    },
}
