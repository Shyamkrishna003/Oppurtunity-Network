from django.urls import path, re_path

from communities.api import views

_UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

urlpatterns = [
    path("communities/", views.CommunityListView.as_view(), name="community-list"),
    path("communities/mine/", views.MyCommunitiesView.as_view(), name="community-mine"),
    path(
        "communities/<uuid:community_id>/",
        views.CommunityDetailView.as_view(),
        name="community-detail",
    ),
    path(
        "communities/<uuid:community_id>/rules/",
        views.RulesView.as_view(),
        name="community-rules",
    ),
    path("communities/<uuid:community_id>/join/", views.JoinView.as_view(), name="community-join"),
    path(
        "communities/<uuid:community_id>/leave/",
        views.LeaveView.as_view(),
        name="community-leave",
    ),
    path(
        "communities/<uuid:community_id>/members/",
        views.MemberListView.as_view(),
        name="community-members",
    ),
    path(
        "communities/<uuid:community_id>/members/<uuid:member_id>/",
        views.MemberDetailView.as_view(),
        name="community-member",
    ),
    # Only the five known actions match; anything else is a 404, not a lookup failure.
    re_path(
        rf"^communities/(?P<community_id>{_UUID})/members/(?P<member_id>{_UUID})/"
        r"(?P<action>approve|reject|remove|ban|unban)/$",
        views.MemberActionView.as_view(),
        name="community-member-action",
    ),
    path(
        "communities/<uuid:community_id>/invitations/",
        views.InvitationView.as_view(),
        name="community-invitations",
    ),
    path(
        "communities/<uuid:community_id>/audit-logs/",
        views.AuditLogView.as_view(),
        name="community-audit-logs",
    ),
]
