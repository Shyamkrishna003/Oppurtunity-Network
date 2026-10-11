from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from applications import policies, selectors, services
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
    """One move in an application's history.

    Who made a move and the note they left with it are for the people deciding on the
    application. For the applicant both are always empty: they see what happened and when.
    """

    from_status = serializers.ChoiceField(choices=ApplicationStatus.choices, allow_blank=True)
    to_status = serializers.ChoiceField(choices=ApplicationStatus.choices)
    note = serializers.SerializerMethodField()
    actor = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationStatusHistory
        fields = ("from_status", "to_status", "created_at", "note", "actor")

    def get_note(self, step: ApplicationStatusHistory) -> str:
        return step.note if self.context.get("show_notes") else ""

    @extend_schema_field(PersonSerializer(allow_null=True))
    def get_actor(self, step: ApplicationStatusHistory) -> Any:
        if not self.context.get("show_notes") or step.actor is None:
            return None
        return PersonSerializer(step.actor).data


class ApplicationViewerSerializer(serializers.Serializer[Any]):
    """What the caller may do with this application. The server still enforces all of it."""

    is_applicant = serializers.BooleanField()
    can_manage = serializers.BooleanField()
    can_withdraw = serializers.BooleanField()
    can_download_resume = serializers.BooleanField()
    # Where the caller may move it now, in the order to offer them. Empty for the applicant.
    next_statuses = serializers.ListField(
        child=serializers.ChoiceField(choices=ApplicationStatus.choices)
    )


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
        context = {"show_notes": policies.can_read_notes(self.context["actor"])}
        return ApplicationStepSerializer(
            selectors.history_of(application), many=True, context=context
        ).data

    @extend_schema_field(ApplicationViewerSerializer)
    def get_viewer(self, application: Application) -> dict[str, Any]:
        actor: policies.Actor = self.context["actor"]
        return {
            "is_applicant": actor.is_applicant,
            "can_manage": policies.decides(actor),
            "can_withdraw": policies.can_withdraw(actor, application),
            "can_download_resume": policies.can_download_resume(actor, application),
            "next_statuses": policies.next_statuses(actor, application),
        }


class PipelineApplicationSerializer(serializers.ModelSerializer[Application]):
    """An application as a row in its job's pipeline, for the job's managers."""

    applicant = PersonSerializer(read_only=True)
    next_statuses = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = (
            "id",
            "status",
            "created_at",
            "status_changed_at",
            "headline",
            "applicant",
            "next_statuses",
        )

    @extend_schema_field(
        serializers.ListField(child=serializers.ChoiceField(choices=ApplicationStatus.choices))
    )
    def get_next_statuses(self, application: Application) -> list[ApplicationStatus]:
        # Everyone who gets this list manages the job; the only question per row is whether
        # the row is their own application.
        viewer_id = self.context["viewer_id"]
        actor = policies.Actor(is_applicant=application.applicant_id == viewer_id, is_manager=True)
        return policies.next_statuses(actor, application)


class PipelineSummarySerializer(serializers.Serializer[Any]):
    # Keyed by status, every status present.
    counts = serializers.DictField(child=serializers.IntegerField())
    total = serializers.IntegerField()
    openings = serializers.IntegerField()


class TransitionSerializer(serializers.Serializer[Any]):
    to = serializers.ChoiceField(choices=sorted(services.MANAGER_TARGETS))
    # The status the caller was looking at; the move is refused if it has changed since.
    expected_status = serializers.ChoiceField(choices=ApplicationStatus.choices)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class ResumeLinkSerializer(serializers.Serializer[Any]):
    # A path on this server. It stops working after ``expires_in`` seconds.
    url = serializers.CharField()
    expires_in = serializers.IntegerField()
