from typing import Any

from django.core.files.storage import default_storage
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from taxonomy.api.serializers import SkillSerializer
from users import selectors
from users.models import (
    SkillKind,
    User,
    UserBlock,
    UserEducation,
    UserExperience,
    UserProfile,
)
from users.services.profiles import MAX_SKILLS_PER_KIND


def avatar_url(profile: UserProfile) -> str | None:
    return default_storage.url(profile.avatar) if profile.avatar else None


# --- Auth -------------------------------------------------------------------------------


class RegisterSerializer(serializers.Serializer[Any]):
    email = serializers.EmailField(max_length=254)
    # Strength is checked by the service; trimming would silently change the password.
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    display_name = serializers.CharField(max_length=80)


class EmailSerializer(serializers.Serializer[Any]):
    email = serializers.EmailField(max_length=254)


class TokenSerializer(serializers.Serializer[Any]):
    token = serializers.CharField(max_length=1024)


class LoginSerializer(serializers.Serializer[Any]):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, trim_whitespace=False)


class PasswordResetConfirmSerializer(serializers.Serializer[Any]):
    uid = serializers.CharField(max_length=64)
    token = serializers.CharField(max_length=256)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)


class PasswordChangeSerializer(serializers.Serializer[Any]):
    current_password = serializers.CharField(max_length=128, trim_whitespace=False)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)


class DetailSerializer(serializers.Serializer[Any]):
    detail = serializers.CharField()


# --- Profile ----------------------------------------------------------------------------


class ProfileSerializer(serializers.ModelSerializer[UserProfile]):
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = (
            "display_name",
            "headline",
            "bio",
            "avatar_url",
            "country_code",
            "region",
            "city",
            "work_mode_preference",
            "experience_level",
            "visibility",
            "show_contact",
            "show_history",
            "accepts_referral_requests",
        )

    def get_avatar_url(self, profile: UserProfile) -> str | None:
        return avatar_url(profile)

    def validate_country_code(self, value: str) -> str:
        if value and not (len(value) == 2 and value.isascii() and value.isalpha()):
            raise serializers.ValidationError("Use a two-letter country code, such as IN.")
        return value.upper()


class UserSkillsSerializer(serializers.Serializer[Any]):
    has = SkillSerializer(many=True, source=SkillKind.HAS.value)
    interested = SkillSerializer(many=True, source=SkillKind.INTERESTED.value)


class SkillSetSerializer(serializers.Serializer[Any]):
    """Request body for replacing the user's skills."""

    has = serializers.ListField(child=serializers.UUIDField(), max_length=MAX_SKILLS_PER_KIND)
    interested = serializers.ListField(
        child=serializers.UUIDField(), max_length=MAX_SKILLS_PER_KIND
    )


class MeSerializer(serializers.ModelSerializer[User]):
    """The signed-in user's own account and profile."""

    email_verified = serializers.BooleanField(source="is_email_verified")
    profile = ProfileSerializer()
    skills = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "email_verified",
            "platform_role",
            "created_at",
            "profile",
            "skills",
        )

    @extend_schema_field(UserSkillsSerializer)
    def get_skills(self, user: User) -> Any:
        return UserSkillsSerializer(selectors.skills_by_kind(user)).data


class SessionSerializer(serializers.Serializer[Any]):
    access_token = serializers.CharField()
    expires_in = serializers.IntegerField()
    user = MeSerializer()


class _DatedEntrySerializer(serializers.ModelSerializer[Any]):
    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise serializers.ValidationError(
                {"end_date": "The end date is before the start date."}
            )
        return attrs


class ExperienceSerializer(_DatedEntrySerializer):
    class Meta:
        model = UserExperience
        fields = ("id", "title", "organization_name", "start_date", "end_date", "description")


class EducationSerializer(_DatedEntrySerializer):
    class Meta:
        model = UserEducation
        fields = ("id", "institution", "degree", "field_of_study", "start_date", "end_date")


class PublicProfileSerializer(serializers.Serializer[Any]):
    """Another user's profile as the viewer may see it. Hidden sections are null."""

    id = serializers.UUIDField()
    is_self = serializers.BooleanField()
    display_name = serializers.CharField()
    headline = serializers.CharField()
    bio = serializers.CharField()
    avatar_url = serializers.CharField(allow_null=True)
    country_code = serializers.CharField()
    region = serializers.CharField()
    city = serializers.CharField()
    work_mode_preference = serializers.CharField()
    experience_level = serializers.CharField()
    skills = UserSkillsSerializer()
    email = serializers.EmailField(allow_null=True)
    experiences = ExperienceSerializer(many=True, allow_null=True)
    educations = EducationSerializer(many=True, allow_null=True)


class BlockedUserSerializer(serializers.ModelSerializer[UserBlock]):
    id = serializers.UUIDField(source="blocked_id")
    display_name = serializers.CharField(source="blocked.profile.display_name")
    avatar_url = serializers.SerializerMethodField()
    blocked_at = serializers.DateTimeField(source="created_at")

    class Meta:
        model = UserBlock
        fields = ("id", "display_name", "avatar_url", "blocked_at")

    def get_avatar_url(self, block: UserBlock) -> str | None:
        return avatar_url(block.blocked.profile)
