from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from connections import policies
from connections.models import Connection
from connections.policies import State
from organizations.api.serializers import PersonSerializer

STATE_CHOICES = [(state.value, state.value.title()) for state in State]


class ConnectionRequestSerializer(serializers.Serializer[Any]):
    user_id = serializers.UUIDField()


class ConnectionSerializer(serializers.ModelSerializer[Connection]):
    """A connection as the caller sees it: the other person, and which side they are on.

    Needs ``viewer_id`` in the context. Only ever given rows the caller is part of.
    """

    user = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()

    class Meta:
        model = Connection
        fields = ("id", "state", "user", "created_at")

    @extend_schema_field(PersonSerializer)
    def get_user(self, connection: Connection) -> Any:
        mine = connection.user_low_id == self.context["viewer_id"]
        return PersonSerializer(connection.user_high if mine else connection.user_low).data

    @extend_schema_field(serializers.ChoiceField(choices=STATE_CHOICES))
    def get_state(self, connection: Connection) -> str | None:
        return policies.state_for(self.context["viewer_id"], connection)


class ConnectionSummarySerializer(serializers.Serializer[Any]):
    # Requests waiting for the caller's answer.
    incoming = serializers.IntegerField()
