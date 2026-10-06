from django.urls import path, re_path
from drf_spectacular.views import SpectacularAPIView

from common.errors import api_not_found

urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    # Keep last: unknown API paths get the standard error envelope, in DEBUG too.
    re_path(r"^.*$", api_not_found),
]
