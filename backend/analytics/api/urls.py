from django.urls import path

from analytics.api import views

urlpatterns = [
    path("admin/stats/", views.PlatformTotalsView.as_view(), name="admin-stats"),
    path(
        "opportunities/<uuid:opportunity_id>/stats/",
        views.OpportunityNumbersView.as_view(),
        name="opportunity-stats",
    ),
]
