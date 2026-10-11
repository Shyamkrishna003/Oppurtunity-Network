from django.urls import path

from organizations.api import views

urlpatterns = [
    path("organizations/", views.OrganizationListView.as_view(), name="organization-list"),
    path("organizations/mine/", views.MyOrganizationsView.as_view(), name="organization-mine"),
    path(
        "organizations/<uuid:organization_id>/",
        views.OrganizationDetailView.as_view(),
        name="organization-detail",
    ),
    path(
        "organizations/<uuid:organization_id>/members/",
        views.MemberListView.as_view(),
        name="organization-members",
    ),
    path(
        "organizations/<uuid:organization_id>/members/<uuid:member_id>/",
        views.MemberDetailView.as_view(),
        name="organization-member",
    ),
    path(
        "organizations/<uuid:organization_id>/leave/",
        views.LeaveView.as_view(),
        name="organization-leave",
    ),
    path(
        "organizations/<uuid:organization_id>/transfer-ownership/",
        views.TransferOwnershipView.as_view(),
        name="organization-transfer-ownership",
    ),
    path(
        "organizations/<uuid:organization_id>/invitations/",
        views.InvitationListView.as_view(),
        name="organization-invitations",
    ),
    path(
        "organizations/<uuid:organization_id>/invitations/<uuid:invitation_id>/",
        views.InvitationDetailView.as_view(),
        name="organization-invitation",
    ),
    path(
        "organization-invitations/<str:token>/",
        views.ReceivedInvitationView.as_view(),
        name="organization-invitation-received",
    ),
    path(
        "organization-invitations/<str:token>/accept/",
        views.AcceptInvitationView.as_view(),
        name="organization-invitation-accept",
    ),
    path(
        "organization-invitations/<str:token>/decline/",
        views.DeclineInvitationView.as_view(),
        name="organization-invitation-decline",
    ),
]
