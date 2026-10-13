from django.urls import path

from connections.api import views

urlpatterns = [
    path("connections/", views.ConnectionListView.as_view(), name="connection-list"),
    path("connections/summary/", views.ConnectionSummaryView.as_view(), name="connection-summary"),
    path(
        "connections/<uuid:connection_id>/",
        views.ConnectionDetailView.as_view(),
        name="connection-detail",
    ),
    path(
        "connections/<uuid:connection_id>/accept/",
        views.AcceptView.as_view(),
        name="connection-accept",
    ),
    path(
        "connections/<uuid:connection_id>/decline/",
        views.DeclineView.as_view(),
        name="connection-decline",
    ),
]
