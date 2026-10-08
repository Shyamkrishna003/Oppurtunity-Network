from typing import Any
from uuid import UUID

from django.conf import settings
from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from common.errors import BusinessRuleViolation
from common.throttles import ScopedThrottle
from users import policies, selectors
from users.api import serializers
from users.api.utils import current_user
from users.errors import SessionExpired
from users.models import User, UserBlock, UserEducation, UserExperience
from users.permissions import SameOriginRequest
from users.services import auth, profiles


def _session_response(session: auth.Session) -> Response:
    response = Response(
        serializers.SessionSerializer(
            {
                "access_token": session.access_token,
                "expires_in": session.expires_in,
                "user": session.user,
            }
        ).data
    )
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        session.refresh_token,
        max_age=int(settings.REFRESH_TOKEN_LIFETIME.total_seconds()),
        path=settings.REFRESH_COOKIE_PATH,
        secure=settings.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite="Strict",
    )
    return response


def _clear_refresh_cookie(response: Response) -> Response:
    response.delete_cookie(
        settings.REFRESH_COOKIE_NAME, path=settings.REFRESH_COOKIE_PATH, samesite="Strict"
    )
    return response


def _validated(serializer_class: type[BaseSerializer[Any]], request: Request) -> dict[str, Any]:
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    data: dict[str, Any] = serializer.validated_data
    return data


class _PublicAuthView(APIView):
    """Reachable without a session. A stale ``Authorization`` header is ignored, not rejected."""

    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedThrottle]


_EMAIL_SENT = "If that address can be used, we have sent an email to it."


class RegisterView(_PublicAuthView):
    throttle_scope = "auth_register"

    @extend_schema(
        request=serializers.RegisterSerializer, responses={202: serializers.DetailSerializer}
    )
    def post(self, request: Request) -> Response:
        """Create an account. The response does not reveal whether the address was already
        registered; the outcome arrives by email."""
        auth.register(**_validated(serializers.RegisterSerializer, request))
        return Response({"detail": _EMAIL_SENT}, status=status.HTTP_202_ACCEPTED)


class VerifyEmailView(_PublicAuthView):
    throttle_scope = "auth_email"

    @extend_schema(request=serializers.TokenSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        auth.verify_email(**_validated(serializers.TokenSerializer, request))
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResendVerificationView(_PublicAuthView):
    throttle_scope = "auth_email"

    @extend_schema(
        request=serializers.EmailSerializer, responses={202: serializers.DetailSerializer}
    )
    def post(self, request: Request) -> Response:
        auth.resend_verification(**_validated(serializers.EmailSerializer, request))
        return Response({"detail": _EMAIL_SENT}, status=status.HTTP_202_ACCEPTED)


class LoginView(_PublicAuthView):
    throttle_scope = "auth_login"

    @extend_schema(request=serializers.LoginSerializer, responses=serializers.SessionSerializer)
    def post(self, request: Request) -> Response:
        """Returns an access token and sets the refresh cookie."""
        return _session_response(auth.login(**_validated(serializers.LoginSerializer, request)))


class RefreshView(_PublicAuthView):
    permission_classes = [SameOriginRequest]
    throttle_scope = "auth_refresh"

    @extend_schema(request=None, responses=serializers.SessionSerializer)
    def post(self, request: Request) -> Response:
        """Exchange the refresh cookie for a new access token; the cookie is rotated."""
        raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if not raw:
            raise SessionExpired()
        return _session_response(auth.refresh(refresh_token=raw))

    def handle_exception(self, exc: Exception) -> Response:
        response = super().handle_exception(exc)
        if isinstance(exc, SessionExpired):
            _clear_refresh_cookie(response)
        return response


class LogoutView(_PublicAuthView):
    permission_classes = [SameOriginRequest]
    throttle_scope = "auth_refresh"

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        """End the session held in the refresh cookie. Succeeds even if there is none."""
        raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if raw:
            auth.logout(refresh_token=raw)
        return _clear_refresh_cookie(Response(status=status.HTTP_204_NO_CONTENT))


class PasswordResetRequestView(_PublicAuthView):
    throttle_scope = "auth_email"

    @extend_schema(
        request=serializers.EmailSerializer, responses={202: serializers.DetailSerializer}
    )
    def post(self, request: Request) -> Response:
        auth.request_password_reset(**_validated(serializers.EmailSerializer, request))
        return Response({"detail": _EMAIL_SENT}, status=status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(_PublicAuthView):
    throttle_scope = "auth_password"

    @extend_schema(request=serializers.PasswordResetConfirmSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        """Set a new password. Every existing session is ended."""
        auth.confirm_password_reset(
            **_validated(serializers.PasswordResetConfirmSerializer, request)
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordChangeView(APIView):
    throttle_classes = [ScopedThrottle]
    throttle_scope = "auth_password"

    @extend_schema(
        request=serializers.PasswordChangeSerializer, responses=serializers.SessionSerializer
    )
    def post(self, request: Request) -> Response:
        """Change the password. Other sessions are ended; this one gets new tokens."""
        session = auth.change_password(
            user=current_user(request),
            **_validated(serializers.PasswordChangeSerializer, request),
        )
        return _session_response(session)


class MeView(APIView):
    @extend_schema(responses=serializers.MeSerializer)
    def get(self, request: Request) -> Response:
        return Response(serializers.MeSerializer(current_user(request)).data)

    @extend_schema(request=serializers.ProfileSerializer, responses=serializers.MeSerializer)
    def patch(self, request: Request) -> Response:
        """Update profile fields."""
        user = current_user(request)
        serializer = serializers.ProfileSerializer(user.profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profiles.update_profile(user.profile, serializer.validated_data)
        return Response(serializers.MeSerializer(user).data)


class MySkillsView(APIView):
    @extend_schema(
        request=serializers.SkillSetSerializer, responses=serializers.UserSkillsSerializer
    )
    def put(self, request: Request) -> Response:
        """Replace both skill sets: what the user has and what they are interested in."""
        user = current_user(request)
        profiles.replace_skills(user, **_validated(serializers.SkillSetSerializer, request))
        return Response(serializers.UserSkillsSerializer(selectors.skills_by_kind(user)).data)


_AVATAR_UPLOAD_SCHEMA = {
    "type": "object",
    "properties": {"file": {"type": "string", "format": "binary"}},
    "required": ["file"],
}


class MyAvatarView(APIView):
    parser_classes = [MultiPartParser]
    throttle_scope = "upload"

    def get_throttles(self) -> list[BaseThrottle]:
        return [ScopedThrottle()] if self.request.method == "PUT" else []

    @extend_schema(
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {"file": {"type": "string", "format": "binary"}},
            }
        },
        responses=serializers.ProfileSerializer,
    )
    def put(self, request: Request) -> Response:
        """Upload a profile photo (JPEG, PNG or WebP). It is resized and re-encoded."""
        upload = request.FILES.get("file")
        if upload is None:
            raise BusinessRuleViolation(
                "Choose an image to upload.",
                code="file_required",
                errors={"file": ["Choose an image to upload."]},
            )
        profile = profiles.set_avatar(current_user(request).profile, upload)
        return Response(serializers.ProfileSerializer(profile).data)

    @extend_schema(responses=serializers.ProfileSerializer)
    def delete(self, request: Request) -> Response:
        profile = profiles.remove_avatar(current_user(request).profile)
        return Response(serializers.ProfileSerializer(profile).data)


class _OwnHistoryViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[Any],
):
    """Entries of the signed-in user only; another user's entry is a 404."""

    pagination_class = None  # bounded by MAX_HISTORY_ENTRIES
    http_method_names = ["get", "post", "patch", "delete"]
    model: type[UserExperience] | type[UserEducation]

    def get_queryset(self) -> QuerySet[Any]:
        if getattr(self, "swagger_fake_view", False):
            return self.model.objects.none()
        return self.model.objects.filter(user=current_user(self.request))

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        if self.get_queryset().count() >= profiles.MAX_HISTORY_ENTRIES:
            raise BusinessRuleViolation(
                f"You can add at most {profiles.MAX_HISTORY_ENTRIES} entries.",
                code="entry_limit_reached",
            )
        serializer.save(user=current_user(self.request))


class ExperienceViewSet(_OwnHistoryViewSet):
    model = UserExperience
    serializer_class = serializers.ExperienceSerializer


class EducationViewSet(_OwnHistoryViewSet):
    model = UserEducation
    serializer_class = serializers.EducationSerializer


class UserDetailView(APIView):
    @extend_schema(responses=serializers.PublicProfileSerializer)
    def get(self, request: Request, user_id: UUID) -> Response:
        """A user's profile as the caller may see it; 404 if it is not visible to them."""
        viewer = current_user(request)
        user = selectors.get_visible_user(viewer, user_id)
        profile = user.profile
        show_history = policies.can_view_history(viewer, profile)
        payload = {
            "id": user.pk,
            "is_self": user.pk == viewer.pk,
            "display_name": profile.display_name,
            "headline": profile.headline,
            "bio": profile.bio,
            "avatar_url": serializers.avatar_url(profile),
            "country_code": profile.country_code,
            "region": profile.region,
            "city": profile.city,
            "work_mode_preference": profile.work_mode_preference,
            "experience_level": profile.experience_level,
            "skills": selectors.skills_by_kind(user),
            "email": user.email if policies.can_view_contact(viewer, profile) else None,
            "experiences": user.experiences.all() if show_history else None,
            "educations": user.educations.all() if show_history else None,
        }
        return Response(serializers.PublicProfileSerializer(payload).data)


class MyBlocksView(generics.ListAPIView[UserBlock]):
    """Users the caller has blocked, newest first."""

    serializer_class = serializers.BlockedUserSerializer

    def get_queryset(self) -> QuerySet[UserBlock]:
        if getattr(self, "swagger_fake_view", False):
            return UserBlock.objects.none()
        return UserBlock.objects.filter(blocker=current_user(self.request)).select_related(
            "blocked__profile"
        )


class UserBlockView(APIView):
    throttle_scope = "user_block"
    throttle_classes = [ScopedThrottle]

    @extend_schema(request=None, responses={204: None})
    def put(self, request: Request, user_id: UUID) -> Response:
        """Block a user: neither can open the other's profile. Idempotent."""
        blocker = current_user(request)
        blocked = User.objects.filter(pk=user_id, is_active=True).first()
        # A user who has blocked the caller is invisible to them, so looks non-existent here.
        if blocked is None or UserBlock.objects.filter(blocker=blocked, blocked=blocker).exists():
            return Response(status=status.HTTP_204_NO_CONTENT)
        profiles.block_user(blocker=blocker, blocked=blocked)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, user_id: UUID) -> Response:
        profiles.unblock_user(blocker=current_user(request), blocked_id=user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
