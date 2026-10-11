from django.urls import path, re_path

from opportunities.api import distribution_views, views

_UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_ACTIONS = "|".join(distribution_views.SUBMISSION_ACTIONS)

urlpatterns = [
    path(
        "opportunities/<uuid:opportunity_id>/communities/",
        distribution_views.OpportunitySharesView.as_view(),
        name="opportunity-shares",
    ),
    path(
        "opportunities/<uuid:opportunity_id>/communities/options/",
        distribution_views.ShareOptionsView.as_view(),
        name="opportunity-share-options",
    ),
    path(
        "opportunities/<uuid:opportunity_id>/communities/<uuid:community_id>/",
        distribution_views.OpportunityShareDetailView.as_view(),
        name="opportunity-share",
    ),
    path(
        "communities/<uuid:community_id>/opportunities/",
        distribution_views.CommunityOpportunitiesView.as_view(),
        name="community-opportunities",
    ),
    path(
        "communities/<uuid:community_id>/submissions/",
        distribution_views.CommunitySubmissionsView.as_view(),
        name="community-submissions",
    ),
    # Only the known actions match; anything else is a 404, not a lookup failure.
    re_path(
        rf"^communities/(?P<community_id>{_UUID})/submissions/(?P<share_id>{_UUID})/"
        rf"(?P<action>{_ACTIONS})/$",
        distribution_views.SubmissionActionView.as_view(),
        name="community-submission-action",
    ),
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
