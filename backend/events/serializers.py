from typing import Any
from zoneinfo import available_timezones

from rest_framework import serializers

from events.models import EventDetail, EventFormat


class EventDetailSerializer(serializers.ModelSerializer[EventDetail]):
    """The ``event`` object nested in an opportunity, for reading and writing.

    ``online_url`` is the way into the event, so it is only given to the people who manage
    it and to those holding a place (pass ``can_manage`` or ``is_going`` in the context).
    Everyone else gets ``has_online_url`` instead.
    """

    has_online_url = serializers.SerializerMethodField()

    class Meta:
        model = EventDetail
        fields = (
            "event_status",
            "format",
            "start_at",
            "end_at",
            "timezone",
            "venue",
            "online_url",
            "has_online_url",
            "capacity",
            "confirmed_count",
            "registration_opens_at",
            "attendee_visibility",
        )
        read_only_fields = ("event_status", "confirmed_count")

    def get_has_online_url(self, event: EventDetail) -> bool:
        return bool(event.online_url)

    def to_representation(self, instance: EventDetail) -> dict[str, Any]:
        data = super().to_representation(instance)
        if not (self.context.get("can_manage") or self.context.get("is_going")):
            data["online_url"] = ""
        return data

    def validate_timezone(self, value: str) -> str:
        if value and value not in available_timezones():
            raise serializers.ValidationError(
                "Use a time zone name such as Asia/Kolkata or Europe/London."
            )
        return value

    def validate_capacity(self, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise serializers.ValidationError("There must be room for at least one person.")
        return value

    def _existing(self) -> EventDetail | None:
        """The event being edited. When nested in an opportunity update, DRF does not hand
        the nested serializer its instance, so it is taken from the parent's."""
        if self.instance is not None:
            return self.instance
        parent = self.parent
        opportunity = getattr(parent, "instance", None) if parent is not None else None
        return getattr(opportunity, "event", None)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        existing = self._existing()

        def value(field: str) -> Any:
            return attrs[field] if field in attrs else getattr(existing, field, None)

        start, end = value("start_at"), value("end_at")
        if start is not None and end is not None and end <= start:
            raise serializers.ValidationError({"end_at": "The event must end after it starts."})
        if value("format") == EventFormat.ONLINE and value("venue"):
            # Nowhere to go, so a venue left over from an earlier choice must not linger.
            attrs["venue"] = ""
        return attrs
