from django.urls import path

from applications.api import views

urlpatterns = [
    # A job's ID is its opportunity's ID.
    path("jobs/<uuid:opportunity_id>/apply/", views.ApplyView.as_view(), name="job-apply"),
    path("applications/", views.MyApplicationsView.as_view(), name="application-list"),
    path(
        "applications/<uuid:application_id>/",
        views.ApplicationDetailView.as_view(),
        name="application-detail",
    ),
    path(
        "applications/<uuid:application_id>/withdraw/",
        views.WithdrawView.as_view(),
        name="application-withdraw",
    ),
    path(
        "applications/<uuid:application_id>/resume/",
        views.ResumeView.as_view(),
        name="application-resume",
    ),
]
