from django.contrib import admin
from django.urls import include, path

from common import health

urlpatterns = [
    path("healthz", health.liveness, name="healthz"),
    path("readyz", health.readiness, name="readyz"),
    path("admin/", admin.site.urls),
    path("api/v1/", include("config.api_urls")),
]
