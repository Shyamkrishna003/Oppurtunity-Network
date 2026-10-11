from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from applications import policies, selectors
from applications.models import Application, ApplicationStatus, ApplicationStatusHistory
from opportunities.api.serializers import OpportunityOrganizationSerializer
from opportunities.models import Opportunity
from organizations.api.serializers import PersonSerializer


class ApplySerializer(serializers.Serializer[Any]):
    """The text part of an application. The resume travels as a file in the same request."""

    cover_note = serializers.CharField(
        max_length=4000, required=False, allow_blank=True, default=""
    )


class ApplicationJobSerializer(serializers.ModelSerializer[Opportunity]):
    """The job an application is for: enough to name it and link to it."""

    organization = OpportunityOrganizationSerializer(read_only=True)

    class Meta:
        model = Opportunity
        fields = ("id", "title", "status", "organization")


class ApplicationSerializer(serializers.ModelSerializer[Application]):
    opportunity = ApplicationJobSerializer(read_only=True)

    class Meta:
        model = Application
        fields: tuple[str, ...] = (
            "id",
            "status",
            "created_at",
            "status_changed_at",
            "opportunity",
        )


class ApplicationStepSerializer(serializers.ModelSerializer[ApplicationStatusHistory]):
    """One move in an application's history. The note a manager may have written with it is
    for the other managers and is not part of this."""

    from_status = serializers.ChoiceField(choices=ApplicationStatus.choices, allow_blank=True)
    to_status = serializers.ChoiceField(choices=ApplicationStatus.choices)

    class Meta:
        model = ApplicationStatusHistory
        fields = ("from_status", "to_status", "created_at")


class ApplicationViewerSerializer(serializers.Serializer[Any]):
    """What the caller may do with this application. The server still enforces all of it."""

    is_applicant = serializers.BooleanField()
    can_manage = serializers.BooleanField()
    can_withdraw = serializers.BooleanField()
    can_download_resume = serializers.BooleanField()


class ApplicationDetailSerializer(ApplicationSerializer):
    applicant = PersonSerializer(read_only=True)
    history = serializers.SerializerMethodField()
    viewer = serializers.SerializerMethodField()

    class Meta(ApplicationSerializer.Meta):
        fields = (
            *ApplicationSerializer.Meta.fields,
            "cover_note",
            "headline",
            "applicant",
            "history",
            "viewer",
        )

    @extend_schema_field(ApplicationStepSerializer(many=True))
    def get_history(self, application: Application) -> Any:
        return ApplicationStepSerializer(selectors.history_of(application), many=True).data

    @extend_schema_field(ApplicationViewerSerializer)
    def get_viewer(self, application: Application) -> dict[str, bool]:
        actor: policies.Actor = self.context["actor"]
        return {
            "is_applicant": actor.is_applicant,
            "can_manage": actor.is_manager,
            "can_withdraw": policies.can_withdraw(actor, application),
            "can_download_resume": policies.can_download_resume(actor, application),
        }


class ResumeLinkSerializer(serializers.Serializer[Any]):
    # A path on this server. It stops working after ``expires_in`` seconds.
    url = serializers.CharField()
    expires_in = serializers.IntegerField()
