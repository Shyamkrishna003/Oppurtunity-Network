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
    # Send it to this community's moderators instead of the platform's. Only for an
    # opportunity the community shows, and only from one of its members.
    community_id = serializers.UUIDField(required=False, allow_null=True, default=None)


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
        fields = ("id", "action_type", "reason", "expires_at", "actor", "created_at")


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
        """What the caller could do in answer to this report: actions that fit the target as
        it stands, that the caller's role allows, and that answer a complaint."""
        if report.status not in policies.IN_PROGRESS:
            return []
        open_to = policies.open_to(self.context["viewer"], report.target)
        return sorted(open_to & policies.RESOLVING)


class CommunityReportSerializer(MyReportSerializer):
    """A report as a community's moderators see it. Not who made it: they are the reporter's
    fellow members, and may be the ones it is about."""

    assigned_to = PersonSerializer(allow_null=True)

    class Meta(MyReportSerializer.Meta):
        fields = (*MyReportSerializer.Meta.fields, "assigned_to", "resolution_note")


class CommunityReportDetailSerializer(CommunityReportSerializer):
    # Reports about the same thing still waiting in this community, this one included.
    in_progress_on_target = serializers.SerializerMethodField()
    # Whether the community still shows what was reported, so that it can be removed.
    shown_in_community = serializers.SerializerMethodField()
    # Whether the caller may decide this report. Not if it is about something they manage.
    can_decide = serializers.SerializerMethodField()

    class Meta(CommunityReportSerializer.Meta):
        fields = (
            *CommunityReportSerializer.Meta.fields,
            "in_progress_on_target",
            "shown_in_community",
            "can_decide",
        )

    def get_in_progress_on_target(self, report: Report) -> int:
        return selectors.in_progress_on(report)

    def get_shown_in_community(self, report: Report) -> bool:
        if report.scope_community_id is None:
            return False
        return selectors.is_shown_in(report.scope_community_id, report.target_opportunity_id)

    def get_can_decide(self, report: Report) -> bool:
        viewer = self.context["viewer"]
        moderator = policies.Moderator(
            viewer, manages_target=selectors.is_own(viewer, report.target)
        )
        return report.status in policies.IN_PROGRESS and policies.uninvolved(moderator, report)


class RemoveSerializer(serializers.Serializer[Any]):
    # For the community's other moderators. Whoever shared it is told only that it was removed.
    reason = serializers.CharField(max_length=500, trim_whitespace=True)


class TargetDetailSerializer(serializers.Serializer[Any]):
    """Anything that can be moderated, as a moderator sees it."""

    target = TargetSerializer()
    # How it stands now, in words: "Suspended until 2026-11-01", "Hidden". Empty if nothing.
    standing = serializers.ListField(child=serializers.CharField())
    # What the caller could do to it now.
    possible_actions = serializers.ListField(
        child=serializers.ChoiceField(choices=ActionType.choices)
    )
    # Which of the possible actions take an end time.
    timed_actions = serializers.ListField(child=serializers.ChoiceField(choices=ActionType.choices))
    actions = ActionSerializer(many=True)


class DismissSerializer(serializers.Serializer[Any]):
    note = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")


class ResolveSerializer(serializers.Serializer[Any]):
    action = serializers.ChoiceField(choices=ActionType.choices)
    # Shown to the person, or to the owners of what is acted on.
    reason = serializers.CharField(max_length=500, trim_whitespace=True)
    # For a suspension or a posting restriction: when it lapses. Omit for "until lifted".
    until = serializers.DateTimeField(required=False, allow_null=True, default=None)


class ActSerializer(ResolveSerializer):
    target_type = serializers.ChoiceField(choices=TargetType.choices)
    target_id = serializers.UUIDField()
