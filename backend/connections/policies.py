"""Who may answer a connection request, and how each side sees the pair's row."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from common.state_machine import StateMachine, Transition
from connections.models import Connection, ConnectionStatus

S = ConnectionStatus


@dataclass(frozen=True)
class Party:
    """Which side of a request the person acting is on."""

    is_recipient: bool


def party_for(user_id: UUID, connection: Connection) -> Party:
    return Party(is_recipient=connection.requested_by_id != user_id)


def _by_recipient(actor: Party | None, connection: Connection) -> bool:
    return actor is not None and actor.is_recipient


# Only the person who was asked answers. Nothing leaves ACCEPTED or DECLINED: ending a
# connection, taking a request back, and asking again all delete the row.
ANSWERS = StateMachine(
    "connection",
    [
        Transition(S.REQUESTED, S.ACCEPTED, policy=_by_recipient),
        Transition(S.REQUESTED, S.DECLINED, policy=_by_recipient),
    ],
)


class State(StrEnum):
    """A connection as one of its two people sees it."""

    CONNECTED = "CONNECTED"
    # They asked me; it is waiting for my answer.
    INCOMING = "INCOMING"
    # I asked them.
    OUTGOING = "OUTGOING"


def state_for(user_id: UUID, connection: Connection) -> State | None:
    """What the row is to this person, or ``None`` if it is nothing to them.

    A decline is never announced. To the person who asked, a declined request goes on
    looking like one that has not been answered; to the person who declined, it is gone.
    """
    if connection.status == S.ACCEPTED:
        return State.CONNECTED
    asked = connection.requested_by_id == user_id
    if connection.status == S.REQUESTED:
        return State.OUTGOING if asked else State.INCOMING
    return State.OUTGOING if asked else None


def can_remove(user_id: UUID, connection: Connection) -> bool:
    """Either person ends a connection; whoever asked takes their request back. Someone who
    was asked answers instead, by accepting or declining."""
    return connection.status == S.ACCEPTED or connection.requested_by_id == user_id
