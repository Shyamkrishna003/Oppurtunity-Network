from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from moderation import policies, selectors
from moderation.models import (
    ActionType,
    ModerationAction,
    Report,
    ReportCategory,
    TargetType,
)
from organizations.api.serializers import PersonSerializer


class TargetSerializer(serializers.Serializer[Any]):
    """What a report or an action is about, in words. ``url`` is a path in the web app."""

    type = serializers.ChoiceField(choices=TargetType.choices)
    id = serializers.UUIDField()
    # Called "name" here because serializers already have an attribute called "label".
    name = serializers.CharField(source="label")
    url = serializers.CharField()


class FileReportSerializer(serializers.Serializer[Any]):
    target_type = serializers.ChoiceField(choices=TargetType.choices)
    target_id = serializers.UUIDField()
    category = serializers.ChoiceField(choices=ReportCategory.choices)
    description = serializers.CharField(
        max_length=2000, allow_blank=True, required=False, default="", trim_whitespace=True
    )


class MyReportSerializer(serializers.ModelSerializer[Report]):
    """A report as the person who made it sees it: what, when, and whether it has been
    decided. Not what was decided, and nothing a moderator wrote."""

    target = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields: tuple[str, ...] = (
            "id",
            "target",
            "category",
            "description",
            "status",
            "created_at",
            "resolved_at",
        )

    @extend_schema_field(TargetSerializer)
    def get_target(self, report: Report) -> Any:
        return TargetSerializer(selectors.describe(report.target)).data


class ReportSerializer(MyReportSerializer):
    """A report as the moderators see it."""

    reporter = PersonSerializer()
    assigned_to = PersonSerializer(allow_null=True)

    class Meta(MyReportSerializer.Meta):
        fields = (
            *MyReportSerializer.Meta.fields,
            "reporter",
            "assigned_to",
            "resolution_note",
        )


class ActionSerializer(serializers.ModelSerializer[ModerationAction]):
    actor = PersonSerializer()

    class Meta:
        model = ModerationAction
        fields = ("id", "action_type", "reason", "actor", "created_at")


class ReportDetailSerializer(ReportSerializer):
    """One report with what a moderator needs to decide it."""

    # Reports about the same thing that are still waiting, this one included.
    in_progress_on_target = serializers.SerializerMethodField()
    # What has already been done to the target, newest first.
    actions = serializers.SerializerMethodField()
    # What could be done about it now, in answer to this report.
    available_actions = serializers.SerializerMethodField()

    class Meta(ReportSerializer.Meta):
        fields = (
            *ReportSerializer.Meta.fields,
            "in_progress_on_target",
            "actions",
            "available_actions",
        )

    def get_in_progress_on_target(self, report: Report) -> int:
        return selectors.in_progress_on(report)

    @extend_schema_field(ActionSerializer(many=True))
    def get_actions(self, report: Report) -> Any:
        return ActionSerializer(selectors.actions_on(report)[:20], many=True).data

    @extend_schema_field(
        serializers.ListField(child=serializers.ChoiceField(choices=ActionType.choices))
    )
    def get_available_actions(self, report: Report) -> list[str]:
        if report.status not in policies.IN_PROGRESS:
            return []
        possible = policies.ACTIONS_FOR[TargetType(report.target_type)] & policies.RESOLVING
        if report.target_type == TargetType.OPPORTUNITY:
            current = report.target_opportunity.moderation_status  # type: ignore[union-attr]
            possible = frozenset(
                action
                for action in possible
                if current in policies.OPPORTUNITY_ALLOWED_FROM[action]
            )
        return sorted(possible)


class DismissSerializer(serializers.Serializer[Any]):
    note = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")


class ResolveSerializer(serializers.Serializer[Any]):
    action = serializers.ChoiceField(choices=ActionType.choices)
    # Shown to the owners of what is acted on.
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class ActSerializer(ResolveSerializer):
    target_type = serializers.ChoiceField(choices=TargetType.choices)
    target_id = serializers.UUIDField()
