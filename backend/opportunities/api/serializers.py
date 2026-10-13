from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from applications.models import ApplicationStatus
from common.choices import ExperienceLevel, WorkMode
from communities.api.serializers import CommunityRefSerializer
from jobs.models import EmploymentType
from jobs.serializers import JobDetailSerializer
from opportunities import policies
from opportunities.distribution import MAX_COMMUNITIES_PER_SHARE
from opportunities.feed import SCOPES, SORTS
from opportunities.models import (
    CloseReason,
    DistributionStatus,
    Opportunity,
    OpportunityCommunity,
    OpportunityType,
    SavedOpportunity,
)
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


class ViewerApplicationSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=ApplicationStatus.choices)


class OpportunityViewerSerializer(serializers.Serializer[Any]):
    """What the caller may do with this opportunity. The server still enforces all of it."""

    can_manage = serializers.BooleanField()
    # Fields the caller may still edit: null means all of them, an empty list means none.
    editable_fields = serializers.ListField(child=serializers.CharField(), allow_null=True)
    is_saved = serializers.BooleanField()
    # Jobs only. ``application`` is the caller's own, if they ever applied to this job.
    can_apply = serializers.BooleanField()
    application = ViewerApplicationSerializer(allow_null=True)
    # An organization's job that is applied to here, and still open. It does not say
    # whether the caller knows anyone at the organization.
    can_request_referral = serializers.BooleanField()


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
    communities = serializers.SerializerMethodField()

    class Meta(OpportunitySerializer.Meta):
        fields = (
            *OpportunitySerializer.Meta.fields,
            "moderation_status",
            "communities",
            "viewer",
        )

    @extend_schema_field(CommunityRefSerializer(many=True))
    def get_communities(self, opportunity: Opportunity) -> Any:
        """Communities showing this opportunity, among those the caller may see."""
        return CommunityRefSerializer(self.context.get("communities", []), many=True).data

    @extend_schema_field(OpportunityViewerSerializer)
    def get_viewer(self, opportunity: Opportunity) -> dict[str, Any]:
        can_manage: bool = self.context.get("can_manage", False)
        editable = policies.editable_fields(opportunity)
        return {
            "can_manage": can_manage,
            "editable_fields": (None if editable is None else sorted(editable))
            if can_manage
            else [],
            "is_saved": self.context.get("is_saved", False),
            "can_apply": self.context.get("can_apply", False),
            "application": ViewerApplicationSerializer(self.context.get("application")).data
            if self.context.get("application")
            else None,
            "can_request_referral": self.context.get("can_request_referral", False),
        }


# --- Feed and saved ---------------------------------------------------------------------


class FeedQuerySerializer(serializers.Serializer[Any]):
    """The feed's URL parameters. Every one is optional; unknown values are a 400."""

    q = serializers.CharField(required=False, max_length=120, help_text="Search text.")
    type = serializers.ChoiceField(choices=OpportunityType.choices, required=False)
    skill = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        max_length=MAX_SKILLS,
        help_text="Repeatable. Matches opportunities needing any of these skills.",
    )
    country = serializers.RegexField(r"^[A-Za-z]{2}$", required=False)
    city = serializers.CharField(required=False, max_length=80)
    work_mode = serializers.ChoiceField(choices=WorkMode.choices, required=False)
    experience_level = serializers.ChoiceField(choices=ExperienceLevel.choices, required=False)
    employment_type = serializers.ChoiceField(choices=EmploymentType.choices, required=False)
    community = serializers.UUIDField(required=False)
    organization = serializers.UUIDField(required=False)
    deadline_before = serializers.DateTimeField(required=False)
    deadline_after = serializers.DateTimeField(required=False)
    posted_within = serializers.IntegerField(
        required=False, min_value=1, max_value=365, help_text="Days."
    )
    saved = serializers.BooleanField(required=False)
    scope = serializers.ChoiceField(
        choices=SCOPES, required=False, help_text="communities: only from communities I am in."
    )
    sort = serializers.ChoiceField(
        choices=SORTS,
        required=False,
        help_text="Default: relevant when searching, otherwise newest.",
    )


class MatchReasonSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(
        choices=("skill", "interest", "community", "location", "work_mode")
    )

    def get_fields(self) -> dict[str, Any]:
        # "label" cannot be declared as a class attribute: serializers already have one.
        return {**super().get_fields(), "label": serializers.CharField()}


class MatchSerializer(serializers.Serializer[Any]):
    """Why this opportunity fits the caller: a fixed sum over what they told us."""

    score = serializers.IntegerField()
    reasons = MatchReasonSerializer(many=True)


class FeedItemSerializer(OpportunitySerializer):
    is_saved = serializers.BooleanField(read_only=True)
    match = serializers.SerializerMethodField()

    class Meta(OpportunitySerializer.Meta):
        fields = (*OpportunitySerializer.Meta.fields, "is_saved", "match")

    @extend_schema_field(MatchSerializer(allow_null=True))
    def get_match(self, opportunity: Opportunity) -> Any:
        """Null for visitors: there is no profile to match against."""
        match = self.context.get("matches", {}).get(opportunity.pk)
        return MatchSerializer(match).data if match is not None else None


class SavedOpportunitySerializer(serializers.ModelSerializer[SavedOpportunity]):
    saved_at = serializers.DateTimeField(source="created_at")
    opportunity = OpportunitySerializer()

    class Meta:
        model = SavedOpportunity
        fields = ("saved_at", "opportunity")


# --- Sharing with communities -----------------------------------------------------------


class ShareRequestSerializer(serializers.Serializer[Any]):
    community_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=MAX_COMMUNITIES_PER_SHARE
    )


class ShareSerializer(serializers.ModelSerializer[OpportunityCommunity]):
    """One community the opportunity was offered to, as its managers see it."""

    community = CommunityRefSerializer()

    class Meta:
        model = OpportunityCommunity
        fields = ("id", "community", "status", "rejection_reason", "is_featured", "created_at")


class ShareOptionSerializer(serializers.Serializer[Any]):
    """One of the caller's communities and what sharing into it would do."""

    community = CommunityRefSerializer()
    current = serializers.ChoiceField(choices=DistributionStatus.choices, allow_null=True)
    # APPROVED: shown at once. PENDING: goes to the community's review. null: not allowed.
    outcome = serializers.ChoiceField(choices=DistributionStatus.choices, allow_null=True)


class CommunityOpportunitySerializer(serializers.ModelSerializer[OpportunityCommunity]):
    """An opportunity in a community's list."""

    share_id = serializers.UUIDField(source="pk")
    opportunity = OpportunitySerializer()

    class Meta:
        model = OpportunityCommunity
        fields = ("share_id", "is_featured", "opportunity")


class SubmissionSerializer(serializers.ModelSerializer[OpportunityCommunity]):
    """A share as the community's moderators see it, in any state."""

    opportunity = OpportunitySerializer()
    submitted_by = PersonSerializer(allow_null=True)

    class Meta:
        model = OpportunityCommunity
        fields = (
            "id",
            "status",
            "is_featured",
            "rejection_reason",
            "created_at",
            "reviewed_at",
            "submitted_by",
            "opportunity",
        )


class RejectSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
