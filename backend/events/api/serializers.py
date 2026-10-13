from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from events import selectors
from events.models import EventDetail, EventRegistration, RegistrationStatus
from opportunities.models import Opportunity, OpportunityStatus
from organizations.api.serializers import PersonSerializer


class MyRegistrationSerializer(serializers.ModelSerializer[EventRegistration]):
    """The caller's own registration for an event."""

    waitlist_position = serializers.SerializerMethodField()

    class Meta:
        model = EventRegistration
        fields = ("id", "status", "waitlist_position", "created_at", "updated_at")

    @extend_schema_field(serializers.IntegerField(allow_null=True, min_value=1))
    def get_waitlist_position(self, registration: EventRegistration) -> int | None:
        return selectors.waitlist_position(registration)


class RegistrationSerializer(serializers.ModelSerializer[EventRegistration]):
    """One person in an event's list, as its organizers see it."""

    person = PersonSerializer(source="user")

    class Meta:
        model = EventRegistration
        fields = ("id", "status", "person", "waitlisted_at", "created_at")


class RegistrationSummarySerializer(serializers.Serializer[Any]):
    counts = serializers.DictField(child=serializers.IntegerField())
    capacity = serializers.IntegerField(allow_null=True)


class _EventOrganizationSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    name = serializers.CharField()


class _MyEventSerializer(serializers.ModelSerializer[EventDetail]):
    """Enough of an event to list it among the ones someone is going to."""

    id = serializers.UUIDField(source="opportunity.pk")
    title = serializers.CharField(source="opportunity.title")
    status = serializers.ChoiceField(source="opportunity.status", choices=OpportunityStatus.choices)
    city = serializers.CharField(source="opportunity.city")
    organization = serializers.SerializerMethodField()

    class Meta:
        model = EventDetail
        fields = (
            "id",
            "title",
            "status",
            "event_status",
            "format",
            "start_at",
            "end_at",
            "timezone",
            "venue",
            "city",
            "organization",
        )

    @extend_schema_field(_EventOrganizationSerializer(allow_null=True))
    def get_organization(self, event: EventDetail) -> Any:
        opportunity: Opportunity = event.opportunity
        if opportunity.organization is None:
            return None
        return {"id": opportunity.organization.pk, "name": opportunity.organization.name}


class MyEventRegistrationSerializer(serializers.ModelSerializer[EventRegistration]):
    event = _MyEventSerializer()
    status = serializers.ChoiceField(choices=RegistrationStatus.choices)

    class Meta:
        model = EventRegistration
        fields = ("id", "status", "created_at", "event")
