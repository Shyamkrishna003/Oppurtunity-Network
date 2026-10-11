from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from communities import policies
from communities.models import (
    Community,
    CommunityMember,
    CommunityRole,
    CommunityRule,
    JoinPolicy,
    MemberStatus,
)
from communities.services import MAX_RULES
from organizations.api.serializers import PersonSerializer

JOIN_ACTIONS = ("join", "request", "accept")


class CommunityWriteSerializer(serializers.ModelSerializer[Community]):
    class Meta:
        model = Community
        fields = ("name", "description", "category", "join_policy", "posting_policy", "visibility")

    def validate_name(self, value: str) -> str:
        name = " ".join(value.split())
        if not any(char.isalnum() for char in name):
            raise serializers.ValidationError("Enter a name with letters or digits.")
        return name

    def validate_category(self, value: str) -> str:
        return " ".join(value.split())


class RuleSerializer(serializers.ModelSerializer[CommunityRule]):
    class Meta:
        model = CommunityRule
        fields = ("title", "body")


class RulesSerializer(serializers.Serializer[Any]):
    rules = RuleSerializer(many=True)

    def validate_rules(self, value: list[dict[str, str]]) -> list[dict[str, str]]:
        if len(value) > MAX_RULES:
            raise serializers.ValidationError(f"A community can have at most {MAX_RULES} rules.")
        return value


class CommunityViewerSerializer(serializers.Serializer[Any]):
    """What the caller is and may do in this community, so the UI can show the right
    controls. The server still enforces every one of these."""

    membership_id = serializers.UUIDField(allow_null=True)
    status = serializers.ChoiceField(choices=MemberStatus.choices, allow_null=True)
    role = serializers.ChoiceField(choices=CommunityRole.choices, allow_null=True)
    join_action = serializers.ChoiceField(choices=JOIN_ACTIONS, allow_null=True)
    can_manage = serializers.BooleanField()
    can_review_requests = serializers.BooleanField()
    assignable_roles = serializers.ListField(
        child=serializers.ChoiceField(choices=CommunityRole.choices)
    )


class CommunitySerializer(serializers.ModelSerializer[Community]):
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Community
        fields: tuple[str, ...] = (
            "id",
            "name",
            "slug",
            "description",
            "category",
            "join_policy",
            "posting_policy",
            "visibility",
            "is_verified",
            "status",
            "member_count",
            "created_at",
        )


def _join_action(community: Community, membership: CommunityMember | None) -> str | None:
    """What pressing "join" would do for this viewer, or None if they cannot."""
    status = membership.status if membership else None
    if status == MemberStatus.INVITED:
        return "accept"
    if status in (MemberStatus.ACTIVE, MemberStatus.PENDING, MemberStatus.BANNED):
        return None
    if community.join_policy == JoinPolicy.OPEN:
        return "join"
    return "request" if community.join_policy == JoinPolicy.APPROVAL else None


class CommunityDetailSerializer(CommunitySerializer):
    rules = RuleSerializer(many=True, read_only=True)
    viewer = serializers.SerializerMethodField()

    class Meta(CommunitySerializer.Meta):
        fields = (*CommunitySerializer.Meta.fields, "rules", "viewer")

    @extend_schema_field(CommunityViewerSerializer)
    def get_viewer(self, community: Community) -> dict[str, Any]:
        membership: CommunityMember | None = self.context.get("membership")
        user_id = membership.user_id if membership else None
        actor = policies.actor_for(user_id, membership) if user_id else None
        is_active = actor is not None and policies.is_member(actor)
        return {
            "membership_id": membership.pk if membership else None,
            # Only states the person should know about; "removed" and the like read as none.
            "status": membership.status
            if membership and membership.status in _SHOWN_STATUSES
            else None,
            "role": membership.role if membership and is_active else None,
            "join_action": _join_action(community, membership),
            "can_manage": bool(actor and policies.can_manage(actor)),
            "can_review_requests": bool(actor and policies.can_review_requests(actor)),
            "assignable_roles": sorted(policies.assignable_roles(actor)) if actor else [],
        }


_SHOWN_STATUSES = (
    MemberStatus.ACTIVE,
    MemberStatus.INVITED,
    MemberStatus.PENDING,
    MemberStatus.BANNED,
)


class CommunityRefSerializer(serializers.ModelSerializer[Community]):
    class Meta:
        model = Community
        fields = ("id", "name", "slug")


class MyCommunitySerializer(serializers.ModelSerializer[CommunityMember]):
    """One of the caller's own memberships, invitations or pending requests."""

    membership_id = serializers.UUIDField(source="pk")
    community = CommunityRefSerializer()

    class Meta:
        model = CommunityMember
        fields = ("membership_id", "community", "role", "status")


class CommunityMemberSerializer(serializers.ModelSerializer[CommunityMember]):
    user = PersonSerializer()

    class Meta:
        model = CommunityMember
        fields = ("id", "user", "role", "status", "joined_at")


class RoleSerializer(serializers.Serializer[Any]):
    role = serializers.ChoiceField(choices=CommunityRole.choices)


class InviteSerializer(serializers.Serializer[Any]):
    user_id = serializers.UUIDField()
