"""Checking people in at the door.

An attendee shows a code; an organizer's device sends it here. The code is not stored
anywhere: it is the registration's ID and serial, signed with the server's secret, so it
cannot be made up or altered, and it stops working the moment the place is given up.
Whether someone is checked in is only ever decided here, from a verified code. The API has
no way to set it directly.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from audit.services import record
from common.errors import BusinessRuleViolation, Conflict
from events import selectors
from events.models import EventDetail, EventRegistration, EventStatus, RegistrationStatus
from users.models import User

_SALT = "events.checkin"
# A signed code is about 90 characters; anything much longer is not one of ours.
MAX_CODE_LENGTH = 300

_INVALID = "This code is not valid for this event."


def code_for(registration: EventRegistration) -> str:
    """The code a person shows at the door. Only meaningful while they hold a place.

    The same every time it is asked for, until the place is given up: no time is signed
    into it, since what ends a code's life is the serial, not the clock.
    """
    return _signer().sign_object([str(registration.pk), registration.checkin_serial])


def _signer() -> signing.Signer:
    return signing.Signer(salt=_SALT)


def _read(code: str) -> tuple[UUID, int] | None:
    if len(code) > MAX_CODE_LENGTH:
        return None
    try:
        registration_id, serial = _signer().unsign_object(code)
        return UUID(registration_id), int(serial)
    except signing.BadSignature, ValueError, TypeError:
        return None


def window(event: EventDetail) -> tuple[datetime, datetime] | None:
    """When people can be checked in: from a while before the start until the end."""
    if event.start_at is None or event.end_at is None:
        return None
    return event.start_at - settings.EVENT_CHECKIN_OPENS_BEFORE, event.end_at


def is_open(event: EventDetail, now: datetime) -> bool:
    opens_closes = window(event)
    if opens_closes is None or event.event_status in ("", EventStatus.CANCELLED):
        return False
    opens, closes = opens_closes
    return opens <= now <= closes


@dataclass(frozen=True)
class CheckIn:
    registration: EventRegistration
    # False when this person had already been checked in, by this or another scan.
    newly: bool


def check_in(*, actor: User, opportunity_id: UUID, code: str) -> CheckIn:
    """Check in the person whose code this is. The caller must manage the event.

    Scanning the same code twice does not check anyone in twice: the second scan answers
    with a conflict that says when the first one happened.
    """
    opportunity = selectors.get_managed_event(actor, opportunity_id)
    event: EventDetail = opportunity.event
    now = timezone.now()
    if not is_open(event, now):
        raise BusinessRuleViolation(
            "Check-in is not open for this event right now.", code="checkin_closed"
        )

    # A forged code, an altered one, one for another event and one from an earlier stay are
    # all answered the same way: nothing is revealed about what exists.
    read = _read(code)
    registration = (
        EventRegistration.objects.select_related("user__profile")
        .filter(pk=read[0], event_id=opportunity.pk, checkin_serial=read[1])
        .first()
        if read is not None
        else None
    )
    if registration is None:
        raise BusinessRuleViolation(_INVALID, code="invalid_code")
    if registration.status != RegistrationStatus.CONFIRMED:
        raise BusinessRuleViolation(
            "This person no longer has a place at this event.", code="not_registered"
        )

    with transaction.atomic():
        # One statement decides it: of two devices scanning at once, exactly one row is
        # updated, and only that one writes the audit record.
        updated = EventRegistration.objects.filter(
            pk=registration.pk,
            status=RegistrationStatus.CONFIRMED,
            checkin_serial=registration.checkin_serial,
            checked_in_at__isnull=True,
        ).update(checked_in_at=now, checked_in_by=actor, updated_at=now)
        if updated:
            record(
                action="event.checked_in",
                target=registration,
                actor=actor,
                organization_id=opportunity.organization_id,
                metadata={"opportunity_id": str(opportunity.pk)},
            )
    registration.refresh_from_db()
    if not updated and registration.checked_in_at is None:
        # Not checked in, yet not updated: the place was given up in this instant.
        raise BusinessRuleViolation(
            "This person no longer has a place at this event.", code="not_registered"
        )
    return CheckIn(registration, newly=bool(updated))


def already(checked: CheckIn) -> Conflict:
    """The answer to a repeated scan, carrying when the person was first checked in."""
    assert checked.registration.checked_in_at is not None
    when = checked.registration.checked_in_at.isoformat()
    return Conflict(
        "This person has already been checked in.",
        code="already_checked_in",
        errors={"checked_in_at": [when]},
    )
