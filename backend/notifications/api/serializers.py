from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from notifications.catalog import DESCRIPTIONS, Rendered, render
from notifications.models import Category, Notification
from organizations.api.serializers import PersonSerializer


class NotificationSerializer(serializers.ModelSerializer[Notification]):
    """A notification, already worded. ``url`` is a path in the web app."""

    title = serializers.SerializerMethodField()
    body = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    actor = PersonSerializer(allow_null=True)
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ("id", "type", "title", "body", "url", "actor", "is_read", "created_at")

    def _rendered(self, notification: Notification) -> Rendered:
        # Worded once per notification, not once per field. One serializer instance handles
        # a whole list, so remembering the last one is enough.
        last: tuple[Any, Rendered] | None = getattr(self, "_last_rendered", None)
        if last is None or last[0] != notification.pk:
            last = (notification.pk, render(notification))
            self._last_rendered = last
        return last[1]

    def get_title(self, notification: Notification) -> str:
        return self._rendered(notification).title

    def get_body(self, notification: Notification) -> str:
        return self._rendered(notification).body

    def get_url(self, notification: Notification) -> str:
        return self._rendered(notification).url

    def get_is_read(self, notification: Notification) -> bool:
        return notification.read_at is not None


class UnreadCountSerializer(serializers.Serializer[Any]):
    count = serializers.IntegerField()


class PreferenceSerializer(serializers.Serializer[Any]):
    category = serializers.ChoiceField(choices=Category.choices)
    in_app = serializers.BooleanField()
    email = serializers.BooleanField()
    title = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()

    @extend_schema_field(serializers.CharField())
    def get_title(self, preference: dict[str, Any]) -> str:
        return str(Category(preference["category"]).label)

    @extend_schema_field(serializers.CharField())
    def get_description(self, preference: dict[str, Any]) -> str:
        return DESCRIPTIONS[Category(preference["category"])]


class PreferencesSerializer(serializers.Serializer[Any]):
    preferences = PreferenceSerializer(many=True)

    def validate_preferences(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        categories = [item["category"] for item in value]
        if len(categories) != len(set(categories)):
            raise serializers.ValidationError("Each category may appear only once.")
        return value
