from django.urls import path

from referrals.api import views

urlpatterns = [
    # A job's ID is its opportunity's ID.
    path(
        "jobs/<uuid:opportunity_id>/eligible-referrers/",
        views.EligibleReferrersView.as_view(),
        name="job-eligible-referrers",
    ),
    path(
        "jobs/<uuid:opportunity_id>/referral-requests/",
        views.ReferralRequestCreateView.as_view(),
        name="job-referral-requests",
    ),
    path("referrals/requests/", views.ReferralListView.as_view(), name="referral-list"),
    path(
        "referrals/requests/<uuid:referral_id>/",
        views.ReferralDetailView.as_view(),
        name="referral-detail",
    ),
    path(
        "referrals/requests/<uuid:referral_id>/accept/",
        views.AcceptView.as_view(),
        name="referral-accept",
    ),
    path(
        "referrals/requests/<uuid:referral_id>/decline/",
        views.DeclineView.as_view(),
        name="referral-decline",
    ),
    path(
        "referrals/requests/<uuid:referral_id>/cancel/",
        views.CancelView.as_view(),
        name="referral-cancel",
    ),
    path(
        "referrals/requests/<uuid:referral_id>/refer/",
        views.ReferView.as_view(),
        name="referral-refer",
    ),
    path(
        "referrals/requests/<uuid:referral_id>/back-out/",
        views.BackOutView.as_view(),
        name="referral-back-out",
    ),
]
