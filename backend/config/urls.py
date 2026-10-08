from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from common import health

urlpatterns = [
    path("healthz", health.liveness, name="healthz"),
    path("readyz", health.readiness, name="readyz"),
    path("admin/", admin.site.urls),
    path("api/v1/", include("config.api_urls")),
    # Development only (no-op unless DEBUG): production serves media from object storage.
    *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
]
