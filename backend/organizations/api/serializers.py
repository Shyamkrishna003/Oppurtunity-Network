from typing import Any

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from organizations import policies
from organizations.models import (
    InvitationStatus,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    OrganizationRole,
)
from users.api.serializers import avatar_url
from users.models import User


class OrganizationWriteSerializer(serializers.ModelSerializer[Organization]):
    class Meta:
        model = Organization
        fields = ("name", "description", "website", "industry", "country_code", "region", "city")

    def validate_name(self, value: str) -> str:
        name = " ".join(value.split())
        if not any(char.isalnum() for char in name):
            raise serializers.ValidationError("Enter a name with letters or digits.")
        return name

    def validate_country_code(self, value: str) -> str:
        if value and not (len(value) == 2 and value.isascii() and value.isalpha()):
            raise serializers.ValidationError("Use a two-letter country code, such as IN.")
        return value.upper()


class ViewerSerializer(serializers.Serializer[Any]):
    """What the caller is and may do in this organization, so the UI can show the right
    controls. The server still enforces every one of these."""

    membership_id = serializers.UUIDField(allow_null=True)
    role = serializers.ChoiceField(choices=OrganizationRole.choices, allow_null=True)
    is_public = serializers.BooleanField(allow_null=True)
    can_manage = serializers.BooleanField()
    assignable_roles = serializers.ListField(
        child=serializers.ChoiceField(choices=OrganizationRole.choices)
    )


class OrganizationSerializer(serializers.ModelSerializer[Organization]):
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Organization
        fields: tuple[str, ...] = (
            "id",
            "name",
            "slug",
            "description",
            "website",
            "industry",
            "country_code",
            "region",
            "city",
            "verification_status",
            "status",
            "member_count",
            "created_at",
        )


class OrganizationDetailSerializer(OrganizationSerializer):
    viewer = serializers.SerializerMethodField()

    class Meta(OrganizationSerializer.Meta):
        fields = (*OrganizationSerializer.Meta.fields, "viewer")

    @extend_schema_field(ViewerSerializer)
    def get_viewer(self, organization: Organization) -> dict[str, Any]:
        membership: OrganizationMember | None = self.context.get("membership")
        return {
            "membership_id": membership.pk if membership else None,
            "role": membership.role if membership else None,
            "is_public": membership.is_public if membership else None,
            "can_manage": policies.can_manage(membership),
            "assignable_roles": sorted(policies.assignable_roles(membership)),
        }


class OrganizationRefSerializer(serializers.ModelSerializer[Organization]):
    class Meta:
        model = Organization
        fields = ("id", "name", "slug")


class MyOrganizationSerializer(serializers.ModelSerializer[OrganizationMember]):
    """One of the caller's own memberships."""

    membership_id = serializers.UUIDField(source="pk")
    organization = OrganizationRefSerializer()

    class Meta:
        model = OrganizationMember
        fields = ("membership_id", "organization", "role")


class PersonSerializer(serializers.ModelSerializer[User]):
    """The public card of a user: what lists may show regardless of profile visibility."""

    display_name = serializers.CharField(source="profile.display_name")
    headline = serializers.CharField(source="profile.headline")
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "display_name", "headline", "avatar_url")

    def get_avatar_url(self, user: User) -> str | None:
        return avatar_url(user.profile)


class MemberSerializer(serializers.ModelSerializer[OrganizationMember]):
    user = PersonSerializer()

    class Meta:
        model = OrganizationMember
        fields = ("id", "user", "role", "is_public", "joined_at")


class MemberUpdateSerializer(serializers.Serializer[Any]):
    """Managers change ``role``; a member changes their own ``is_public``."""

    role = serializers.ChoiceField(choices=OrganizationRole.choices, required=False)
    is_public = serializers.BooleanField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if len(attrs) != 1:
            raise serializers.ValidationError("Send exactly one of: role, is_public.")
        return attrs


class TransferOwnershipSerializer(serializers.Serializer[Any]):
    member_id = serializers.UUIDField()


class InvitationCreateSerializer(serializers.Serializer[Any]):
    email = serializers.EmailField(max_length=254)
    role = serializers.ChoiceField(choices=OrganizationRole.choices)


class _InvitationStatusMixin(serializers.Serializer[Any]):
    status = serializers.SerializerMethodField()

    @extend_schema_field(serializers.ChoiceField(choices=InvitationStatus.choices))
    def get_status(self, invitation: OrganizationInvitation) -> str:
        # A pending invitation past its time is reported as expired without a write.
        if (
            invitation.status == InvitationStatus.PENDING
            and invitation.expires_at <= timezone.now()
        ):
            return InvitationStatus.EXPIRED
        return invitation.status


class InvitationSerializer(
    _InvitationStatusMixin, serializers.ModelSerializer[OrganizationInvitation]
):
    """An invitation as the organization's managers see it."""

    invited_by = serializers.CharField(
        source="invited_by.profile.display_name", default=None, allow_null=True
    )

    class Meta:
        model = OrganizationInvitation
        fields = ("id", "email", "role", "status", "expires_at", "invited_by", "created_at")


class ReceivedInvitationSerializer(
    _InvitationStatusMixin, serializers.ModelSerializer[OrganizationInvitation]
):
    """An invitation as the invited person sees it."""

    organization = OrganizationRefSerializer()
    invited_by = serializers.CharField(
        source="invited_by.profile.display_name", default=None, allow_null=True
    )

    class Meta:
        model = OrganizationInvitation
        fields = ("organization", "role", "status", "expires_at", "invited_by")
