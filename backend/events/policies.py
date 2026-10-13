"""The state machine for an event's registration and outcome."""

from common.choices import WorkMode
from common.state_machine import StateMachine, Transition
from events.models import EventDetail, EventFormat, EventStatus
from opportunities.policies import Manager

S = EventStatus

# States from which an event can still take place.
UPCOMING = frozenset({S.SCHEDULED, S.REGISTRATION_OPEN, S.REGISTRATION_CLOSED})

# An event has no "work mode" of its own, but people filter and match by one, so the
# opportunity's is kept in step with the event's format.
WORK_MODE_FOR = {
    EventFormat.IN_PERSON: WorkMode.ONSITE,
    EventFormat.ONLINE: WorkMode.REMOTE,
    EventFormat.HYBRID: WorkMode.HYBRID,
}


def _by_manager(actor: Manager | None, event: EventDetail) -> bool:
    return actor is not None


def _by_system(actor: Manager | None, event: EventDetail) -> bool:
    return actor is None


# Reaching capacity is not a state: registration stays open and people join the waitlist.
# The periodic sweep makes the system's moves with conditional updates that mirror these.
EVENT = StateMachine(
    "event",
    [
        Transition(S.SCHEDULED, S.REGISTRATION_OPEN),
        Transition(S.REGISTRATION_OPEN, S.REGISTRATION_CLOSED),
        # Only a person reopens registration, and only while that still makes sense.
        Transition(S.REGISTRATION_CLOSED, S.REGISTRATION_OPEN, policy=_by_manager),
        *(Transition(source, S.COMPLETED, policy=_by_system) for source in UPCOMING),
        *(Transition(source, S.CANCELLED, policy=_by_manager) for source in UPCOMING),
    ],
    field="event_status",
)
