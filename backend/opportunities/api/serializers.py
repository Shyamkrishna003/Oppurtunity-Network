from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from jobs.serializers import JobDetailSerializer
from opportunities import policies
from opportunities.models import CloseReason, Opportunity, OpportunityType
from opportunities.services import MAX_SKILLS
from organizations.api.serializers import PersonSerializer
from organizations.models import Organization
from taxonomy.api.serializers import SkillSerializer


class OpportunityFieldsSerializer(serializers.ModelSerializer[Opportunity]):
    """The shared, editable fields, plus the nested type-specific object and the skills."""

    job = JobDetailSerializer(required=False)
    skill_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, max_length=MAX_SKILLS
    )

    class Meta:
        model = Opportunity
        fields: tuple[str, ...] = (
            "title",
            "description",
            "visibility",
            "work_mode",
            "country_code",
            "region",
            "city",
            "deadline",
            "job",
            "skill_ids",
        )

    def validate_title(self, value: str) -> str:
        title = " ".join(value.split())
        if not any(char.isalnum() for char in title):
            raise serializers.ValidationError("Enter a title with letters or digits.")
        return title

    def validate_country_code(self, value: str) -> str:
        if value and not (len(value) == 2 and value.isascii() and value.isalpha()):
            raise serializers.ValidationError("Use a two-letter country code, such as IN.")
        return value.upper()


class OpportunityCreateSerializer(OpportunityFieldsSerializer):
    type = serializers.ChoiceField(choices=OpportunityType.choices)
    # Omit or null for a personal opportunity.
    organization_id = serializers.UUIDField(required=False, allow_null=True)

    class Meta(OpportunityFieldsSerializer.Meta):
        fields = ("type", "organization_id", *OpportunityFieldsSerializer.Meta.fields)


class CloseSerializer(serializers.Serializer[Any]):
    reason = serializers.ChoiceField(choices=CloseReason.choices)


class OpportunityOrganizationSerializer(serializers.ModelSerializer[Organization]):
    class Meta:
        model = Organization
        fields = ("id", "name", "slug", "verification_status")


class OpportunityViewerSerializer(serializers.Serializer[Any]):
    """What the caller may do with this opportunity. The server still enforces all of it."""

    can_manage = serializers.BooleanField()
    # Fields the caller may still edit: null means all of them, an empty list means none.
    editable_fields = serializers.ListField(child=serializers.CharField(), allow_null=True)


class OpportunitySerializer(serializers.ModelSerializer[Opportunity]):
    organization = OpportunityOrganizationSerializer(read_only=True)
    posted_by = serializers.SerializerMethodField()
    skills = SkillSerializer(many=True, read_only=True)
    job = JobDetailSerializer(read_only=True)

    class Meta:
        model = Opportunity
        fields: tuple[str, ...] = (
            "id",
            "type",
            "title",
            "description",
            "status",
            "visibility",
            "work_mode",
            "country_code",
            "region",
            "city",
            "deadline",
            "published_at",
            "closed_at",
            "close_reason",
            "created_at",
            "organization",
            "posted_by",
            "skills",
            "job",
        )

    @extend_schema_field(PersonSerializer(allow_null=True))
    def get_posted_by(self, opportunity: Opportunity) -> Any:
        # An organization's opportunity speaks for the organization, not for whichever
        # recruiter typed it in.
        if opportunity.organization_id is not None:
            return None
        return PersonSerializer(opportunity.creator).data


class OpportunityDetailSerializer(OpportunitySerializer):
    viewer = serializers.SerializerMethodField()

    class Meta(OpportunitySerializer.Meta):
        fields = (*OpportunitySerializer.Meta.fields, "moderation_status", "viewer")

    @extend_schema_field(OpportunityViewerSerializer)
    def get_viewer(self, opportunity: Opportunity) -> dict[str, Any]:
        can_manage: bool = self.context.get("can_manage", False)
        editable = policies.editable_fields(opportunity)
        return {
            "can_manage": can_manage,
            "editable_fields": (None if editable is None else sorted(editable))
            if can_manage
            else [],
        }
