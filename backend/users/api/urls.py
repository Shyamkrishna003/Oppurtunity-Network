from django.urls import path
from rest_framework.routers import SimpleRouter

from users.api import views

router = SimpleRouter()
router.register("users/me/experiences", views.ExperienceViewSet, basename="experience")
router.register("users/me/educations", views.EducationViewSet, basename="education")

urlpatterns = [
    path("auth/register/", views.RegisterView.as_view(), name="auth-register"),
    path("auth/verify-email/", views.VerifyEmailView.as_view(), name="auth-verify-email"),
    path(
        "auth/verify-email/resend/",
        views.ResendVerificationView.as_view(),
        name="auth-verify-email-resend",
    ),
    path("auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("auth/refresh/", views.RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path(
        "auth/password-reset/",
        views.PasswordResetRequestView.as_view(),
        name="auth-password-reset",
    ),
    path(
        "auth/password-reset/confirm/",
        views.PasswordResetConfirmView.as_view(),
        name="auth-password-reset-confirm",
    ),
    path("auth/password-change/", views.PasswordChangeView.as_view(), name="auth-password-change"),
    path("users/me/", views.MeView.as_view(), name="user-me"),
    path("users/me/skills/", views.MySkillsView.as_view(), name="user-me-skills"),
    path("users/me/avatar/", views.MyAvatarView.as_view(), name="user-me-avatar"),
    path("users/me/blocks/", views.MyBlocksView.as_view(), name="user-me-blocks"),
    *router.urls,
    path("users/<uuid:user_id>/", views.UserDetailView.as_view(), name="user-detail"),
    path("users/<uuid:user_id>/block/", views.UserBlockView.as_view(), name="user-block"),
]
