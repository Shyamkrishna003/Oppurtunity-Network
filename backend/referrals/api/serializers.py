from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from applications.api.serializers import ApplicationJobSerializer
from organizations.api.serializers import PersonSerializer
from referrals import policies, selectors
from referrals.models import ReferralRequest, ReferralStatus, ReferralStatusHistory


class ReferralRequestCreateSerializer(serializers.Serializer[Any]):
    referrer_id = serializers.UUIDField()
    message = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class ReferSerializer(serializers.Serializer[Any]):
    # What the referrer tells the people hiring. A referral without a word is not one.
    endorsement_note = serializers.CharField(min_length=20, max_length=2000)


class ReferralSerializer(serializers.ModelSerializer[ReferralRequest]):
    """A referral as a row in "asked by me" or "asked of me": both people and the job."""

    opportunity = ApplicationJobSerializer(read_only=True)
    requester = PersonSerializer(read_only=True)
    referrer = PersonSerializer(read_only=True)

    class Meta:
        model = ReferralRequest
        fields: tuple[str, ...] = (
            "id",
            "status",
            "created_at",
            "status_changed_at",
            "expires_at",
            "opportunity",
            "requester",
            "referrer",
        )


class ReferralStepSerializer(serializers.ModelSerializer[ReferralStatusHistory]):
    from_status = serializers.ChoiceField(choices=ReferralStatus.choices, allow_blank=True)
    to_status = serializers.ChoiceField(choices=ReferralStatus.choices)

    class Meta:
        model = ReferralStatusHistory
        fields = ("from_status", "to_status", "created_at")


class ReferralViewerSerializer(serializers.Serializer[Any]):
    """What the caller is to this referral and may do with it. The server enforces it."""

    is_requester = serializers.BooleanField()
    is_referrer = serializers.BooleanField()
    # In the order to offer them: accept, decline, cancel, refer, back_out.
    actions = serializers.ListField(child=serializers.CharField())


class ReferralDetailSerializer(ReferralSerializer):
    """One referral with its history. Needs ``actor`` in the context.

    ``message`` is between the two people and is empty for the job's managers;
    ``endorsement_note`` is from the referrer to the managers and is empty for the requester.
    """

    message = serializers.SerializerMethodField()
    endorsement_note = serializers.SerializerMethodField()
    application_id = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()
    viewer = serializers.SerializerMethodField()

    class Meta(ReferralSerializer.Meta):
        fields = (
            *ReferralSerializer.Meta.fields,
            "message",
            "endorsement_note",
            "referred_at",
            "application_id",
            "history",
            "viewer",
        )

    def get_message(self, referral: ReferralRequest) -> str:
        return referral.message if policies.can_read_message(self.context["actor"]) else ""

    def get_endorsement_note(self, referral: ReferralRequest) -> str:
        if policies.can_read_endorsement(self.context["actor"]):
            return referral.endorsement_note
        return ""

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_application_id(self, referral: ReferralRequest) -> Any:
        """The application the referral follows, for those who can open it: the requester
        and the job's managers. The referrer only ever sees the referral's own status."""
        actor: policies.Actor = self.context["actor"]
        return referral.application_id if actor.is_requester or actor.is_manager else None

    @extend_schema_field(ReferralStepSerializer(many=True))
    def get_history(self, referral: ReferralRequest) -> Any:
        return ReferralStepSerializer(selectors.history_of(referral), many=True).data

    @extend_schema_field(ReferralViewerSerializer)
    def get_viewer(self, referral: ReferralRequest) -> dict[str, Any]:
        actor: policies.Actor = self.context["actor"]
        return {
            "is_requester": actor.is_requester,
            "is_referrer": actor.is_referrer,
            "actions": policies.actions(actor, referral),
        }


class EligibleReferrersSerializer(serializers.Serializer[Any]):
    """The caller's own connections they could ask for this job, and how many more requests
    they may have open for it."""

    referrers = PersonSerializer(many=True)
    remaining = serializers.IntegerField()
