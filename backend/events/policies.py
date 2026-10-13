"""The state machines for an event and for a registration, and who may see who is going."""

from dataclasses import dataclass
from datetime import datetime

from common.choices import WorkMode
from common.state_machine import StateMachine, Transition
from events.models import (
    AttendeeVisibility,
    EventDetail,
    EventFormat,
    EventRegistration,
    EventStatus,
    RegistrationStatus,
)
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


def registration_is_open(event: EventDetail, deadline: datetime | None, now: datetime) -> bool:
    """Whether someone can register at this moment.

    Judged from the times as well as the status, so it is right even when the periodic sweep
    is late: nobody gets in before the opening time or after the deadline or the start.
    ``deadline`` is the opportunity's, which is when registration closes.
    """
    if event.event_status == S.SCHEDULED:
        opens = event.registration_opens_at
        if opens is None or opens > now:
            return False
    elif event.event_status != S.REGISTRATION_OPEN:
        return False
    if event.start_at is None or event.start_at <= now:
        return False
    return deadline is None or deadline > now


# --- Registrations ----------------------------------------------------------------------

R = RegistrationStatus
# Holding a place or waiting for one.
ACTIVE = frozenset({R.CONFIRMED, R.WAITLISTED})


@dataclass(frozen=True)
class Registrant:
    """The person a registration belongs to, acting on it themselves."""


@dataclass(frozen=True)
class Organizer:
    """Someone who manages the event, acting on another person's registration."""


RegistrationActor = Registrant | Organizer | None  # None is the system


def _by_registrant(actor: RegistrationActor, registration: EventRegistration) -> bool:
    return isinstance(actor, Registrant)


def _by_person(actor: RegistrationActor, registration: EventRegistration) -> bool:
    return actor is not None


def _promotion(actor: RegistrationActor, registration: EventRegistration) -> bool:
    return actor is None


REGISTRATION = StateMachine(
    "registration",
    [
        # Only the system takes someone off the waitlist, in the order they joined it.
        Transition(R.WAITLISTED, R.CONFIRMED, policy=_promotion),
        Transition(R.CONFIRMED, R.CANCELLED, policy=_by_person),
        Transition(R.WAITLISTED, R.CANCELLED, policy=_by_person),
        # Coming back after cancelling. An organizer cannot put anyone back.
        Transition(R.CANCELLED, R.CONFIRMED, policy=_by_registrant),
        Transition(R.CANCELLED, R.WAITLISTED, policy=_by_registrant),
    ],
)


def can_see_attendees(event: EventDetail, *, is_manager: bool, is_attending: bool) -> bool:
    """Who may see the list of people going, as the organizer chose."""
    if is_manager or event.attendee_visibility == AttendeeVisibility.PUBLIC:
        return True
    return event.attendee_visibility == AttendeeVisibility.ATTENDEES and is_attending
