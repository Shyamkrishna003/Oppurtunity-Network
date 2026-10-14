from django.urls import path

from audit.api import views

urlpatterns = [
    path("admin/audit-logs/", views.AuditLogView.as_view(), name="admin-audit-logs"),
]
