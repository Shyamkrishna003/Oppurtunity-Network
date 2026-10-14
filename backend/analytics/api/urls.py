from django.urls import path

from analytics.api import views

urlpatterns = [
    path("admin/stats/", views.PlatformTotalsView.as_view(), name="admin-stats"),
    path(
        "opportunities/<uuid:opportunity_id>/stats/",
        views.OpportunityNumbersView.as_view(),
        name="opportunity-stats",
    ),
    path(
        "organizations/<uuid:organization_id>/stats/",
        views.OrganizationNumbersView.as_view(),
        name="organization-stats",
    ),
    path(
        "communities/<uuid:community_id>/stats/",
        views.CommunityNumbersView.as_view(),
        name="community-stats",
    ),
]
