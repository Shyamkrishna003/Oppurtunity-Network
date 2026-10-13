from django.urls import path

from moderation.api import views

urlpatterns = [
    path("reports/", views.FileReportView.as_view(), name="report-file"),
    path("reports/mine/", views.MyReportsView.as_view(), name="report-mine"),
    path("moderation/reports/", views.ReportQueueView.as_view(), name="moderation-reports"),
    path(
        "moderation/reports/<uuid:report_id>/",
        views.ReportDetailView.as_view(),
        name="moderation-report",
    ),
    path(
        "moderation/reports/<uuid:report_id>/claim/",
        views.ClaimView.as_view(),
        name="moderation-report-claim",
    ),
    path(
        "moderation/reports/<uuid:report_id>/dismiss/",
        views.DismissView.as_view(),
        name="moderation-report-dismiss",
    ),
    path(
        "moderation/reports/<uuid:report_id>/resolve/",
        views.ResolveView.as_view(),
        name="moderation-report-resolve",
    ),
    path("moderation/actions/", views.ActView.as_view(), name="moderation-actions"),
]
