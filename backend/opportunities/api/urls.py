from django.urls import path

from opportunities.api import views

urlpatterns = [
    path("opportunities/", views.OpportunityCreateView.as_view(), name="opportunity-list"),
    path(
        "opportunities/<uuid:opportunity_id>/",
        views.OpportunityDetailView.as_view(),
        name="opportunity-detail",
    ),
    path(
        "opportunities/<uuid:opportunity_id>/publish/",
        views.PublishView.as_view(),
        name="opportunity-publish",
    ),
    path(
        "opportunities/<uuid:opportunity_id>/close/",
        views.CloseView.as_view(),
        name="opportunity-close",
    ),
    path(
        "opportunities/<uuid:opportunity_id>/archive/",
        views.ArchiveView.as_view(),
        name="opportunity-archive",
    ),
    path(
        "users/me/opportunities/",
        views.MyOpportunitiesView.as_view(),
        name="user-me-opportunities",
    ),
]
