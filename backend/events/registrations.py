"""Registering for events: places, the waitlist, and everything that moves people between them.

One rule holds all of this together: a registration's status, and the event's count of
confirmed places, only ever change inside a transaction that holds a lock on the event's
row. Two people cannot take the last place, a cancellation and a promotion cannot
interleave, and the count always equals the number of confirmed registrations. The check
constraint ``events_not_overbooked`` is the backstop if this code is ever wrong.
"""

from functools import partial
from uuid import UUID

from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from audit.services import record
from common.errors import BusinessRuleViolation, Conflict
from common.tasks import enqueue
from events import policies, selectors
from events.models import EventDetail, EventRegistration, RegistrationStatus
from events.policies import REGISTRATION, Organizer, Registrant
from notifications.models import NotificationType
from notifications.services import notify
from opportunities.models import ModerationStatus, Opportunity, OpportunityStatus
from realtime.tasks import publish_event
from users.models import User

R = RegistrationStatus
CANCEL_NOTICE_BATCH = 500

_CLOSED = "Registration for this event is not open."


def _lock_event(opportunity_id: UUID) -> EventDetail:
    """The event's row, locked: the one lock every change to its registrations takes."""
    event = (
        EventDetail.objects.select_for_update(of=("self",))
        .select_related("opportunity")
        .filter(pk=opportunity_id)
        .first()
    )
    if event is None:
        raise Http404
    return event


def _has_room(event: EventDetail) -> bool:
    return event.capacity is None or event.confirmed_count < event.capacity


def _about(opportunity: Opportunity) -> dict[str, str]:
    return {"opportunity_id": str(opportunity.pk), "opportunity_title": opportunity.title}


def _tell_live(user_id: UUID, registration: EventRegistration) -> None:
    """Nudge the person's open pages to refetch. A hint only; the row is the record."""
    data = {"event_id": str(registration.event_id), "status": registration.status}
    transaction.on_commit(
        partial(enqueue, publish_event, str(user_id), "registration.updated", data)
    )


def _promote(event: EventDetail) -> int:
    """Give free places to the head of the waitlist, in the order people joined it.

    Call with the event locked, after anything that may have freed a place.
    """
    promoted = 0
    waiting = (
        EventRegistration.objects.filter(event=event, status=R.WAITLISTED)
        .select_related("user")
        .order_by("waitlisted_at", "pk")
    )
    opportunity = event.opportunity
    for registration in waiting.iterator(chunk_size=100):
        if not _has_room(event):
            break
        REGISTRATION.apply(registration, R.CONFIRMED, actor=None)
        registration.waitlisted_at = None
        # A new place, so a new check-in code: one from an earlier stay must not work.
        registration.checkin_serial += 1
        registration.save(update_fields=["status", "waitlisted_at", "checkin_serial", "updated_at"])
        event.confirmed_count += 1
        record(
            action="event.registration_promoted",
            target=registration,
            organization_id=opportunity.organization_id,
            metadata={"opportunity_id": str(opportunity.pk)},
        )
        notify(
            recipient=registration.user,
            type=NotificationType.REGISTRATION_PROMOTED,
            target=opportunity,
            payload=_about(opportunity),
        )
        _tell_live(registration.user_id, registration)
        promoted += 1
    if promoted:
        event.save(update_fields=["confirmed_count"])
    return promoted


def register(*, user: User, opportunity_id: UUID) -> tuple[EventRegistration, bool]:
    """Take a place at an event, or join its waitlist if it is full.

    Returns the registration and whether this call changed anything. Registering when
    already going or waiting is not an error: that registration is returned as it is, which
    covers a double click as well as coming back to the page.
    """
    opportunity = selectors.get_event(user, opportunity_id)
    with transaction.atomic():
        event = _lock_event(opportunity.pk)
        registration = EventRegistration.objects.filter(event=event, user=user).first()
        if registration is not None and registration.status in policies.ACTIVE:
            return registration, False

        # Read again now that the event is locked: it may have been cancelled, or its
        # registration closed, since the page was loaded.
        current = event.opportunity
        if (
            current.status != OpportunityStatus.PUBLISHED
            or current.moderation_status != ModerationStatus.VISIBLE
            or not policies.registration_is_open(event, current.deadline, timezone.now())
            or not selectors.can_register(user, opportunity)
        ):
            raise Conflict(_CLOSED, code="registration_closed")

        now = timezone.now()
        status = R.CONFIRMED if _has_room(event) else R.WAITLISTED
        if registration is None:
            registration = EventRegistration(event=event, user=user, status=status)
        else:
            # Back after cancelling: the same row, no place kept in the queue, and a new
            # check-in code.
            REGISTRATION.apply(registration, status, actor=Registrant())
            registration.checkin_serial += 1
        registration.waitlisted_at = now if status == R.WAITLISTED else None
        registration.save()
        if status == R.CONFIRMED:
            event.confirmed_count += 1
            event.save(update_fields=["confirmed_count"])
        record(
            action="event.registered",
            target=registration,
            actor=user,
            organization_id=current.organization_id,
            metadata={"opportunity_id": str(current.pk), "status": status},
        )
        return registration, True


def _release(
    event: EventDetail, registration: EventRegistration, *, by: User, actor: Registrant | Organizer
) -> bool:
    """Cancel a registration and hand its place on. Returns False if it was already cancelled.

    ``registration`` must have been loaded with a row lock, so that a check-in at the door
    cannot land between the check below and the save.
    """
    previous = registration.status
    if registration.checked_in_at is not None:
        raise Conflict(
            "This person has already been checked in, so the registration stays.",
            code="already_checked_in",
        )
    if not REGISTRATION.apply(registration, R.CANCELLED, actor=actor):
        return False
    registration.waitlisted_at = None
    registration.save(update_fields=["status", "waitlisted_at", "updated_at"])
    if previous == R.CONFIRMED:
        event.confirmed_count -= 1
        event.save(update_fields=["confirmed_count"])
    opportunity = event.opportunity
    record(
        action="event.registration_cancelled",
        target=registration,
        actor=by,
        organization_id=opportunity.organization_id,
        metadata={
            "opportunity_id": str(opportunity.pk),
            "from": previous,
            "by": "organizer" if isinstance(actor, Organizer) else "registrant",
        },
    )
    # Only an event that is still to come passes places on.
    if event.event_status in policies.UPCOMING:
        _promote(event)
    return True


def cancel_registration(*, user: User, opportunity_id: UUID) -> EventRegistration:
    """Give up one's own place, or one's place in the queue. Doing it twice changes nothing."""
    with transaction.atomic():
        event = _lock_event(opportunity_id)
        registration = (
            EventRegistration.objects.select_for_update().filter(event=event, user=user).first()
        )
        if registration is None:
            raise Http404
        if registration.status == R.CANCELLED:
            return registration
        if event.start_at is not None and event.start_at <= timezone.now():
            raise Conflict(
                "This event has already started, so the registration can no longer be cancelled.",
                code="event_started",
            )
        _release(event, registration, by=user, actor=Registrant())
        return registration


def remove(*, actor: User, opportunity_id: UUID, registration_id: UUID) -> EventRegistration:
    """An organizer cancels someone's registration. The person is told; no reason is given."""
    opportunity = selectors.get_managed_event(actor, opportunity_id)
    with transaction.atomic():
        event = _lock_event(opportunity.pk)
        registration = (
            EventRegistration.objects.select_for_update(of=("self",))
            .select_related("user")
            .filter(pk=registration_id, event=event)
            .first()
        )
        if registration is None:
            raise Http404
        # Checked again under the lock: they may have stopped managing it a moment ago.
        if not selectors.is_manager(actor, event.opportunity):
            raise PermissionDenied()
        if _release(event, registration, by=actor, actor=Organizer()):
            notify(
                recipient=registration.user,
                type=NotificationType.REGISTRATION_REMOVED,
                target=event.opportunity,
                payload=_about(event.opportunity),
            )
            _tell_live(registration.user_id, registration)
        return registration


def set_capacity(event_id: UUID, capacity: int | None) -> None:
    """Change how many places a published event has.

    It cannot go below the number of people already going: nobody loses a place this way.
    Making room promotes from the waitlist at once. Call inside the opportunity's update.
    """
    event = _lock_event(event_id)
    if capacity is not None and capacity < event.confirmed_count:
        message = (
            f"{event.confirmed_count} people are already going. "
            "Cancel registrations first, or choose a larger number."
        )
        raise BusinessRuleViolation(
            message, code="capacity_below_confirmed", errors={"event.capacity": [message]}
        )
    event.capacity = capacity
    event.save(update_fields=["capacity"])
    _promote(event)


def announce_cancellation(opportunity_id: UUID) -> int:
    """Tell everyone who was going to, or waiting for, a cancelled event. Returns how many.

    Run from a background task: an event can have any number of registrations. Safe to run
    again; each person is told once, however many times this runs.
    """
    opportunity = Opportunity.objects.filter(pk=opportunity_id).first()
    if opportunity is None:
        return 0
    told = 0
    registrations = (
        EventRegistration.objects.filter(event_id=opportunity_id, status__in=policies.ACTIVE)
        .select_related("user")
        .order_by("pk")
    )
    for registration in registrations.iterator(chunk_size=CANCEL_NOTICE_BATCH):
        with transaction.atomic():
            notice = notify(
                recipient=registration.user,
                type=NotificationType.EVENT_CANCELLED,
                target=opportunity,
                payload=_about(opportunity),
                dedupe_key=f"event-cancelled:{opportunity_id}",
            )
        told += notice is not None
    return told
