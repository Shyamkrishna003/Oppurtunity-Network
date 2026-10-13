"""The event-specific half of an opportunity. The create, edit, publish and cancel functions
are called by the opportunity service, inside its transaction; the sweep runs on its own."""

from datetime import datetime
from functools import partial
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from audit.services import record
from common.errors import Conflict, FieldErrors
from common.tasks import enqueue
from events import registrations
from events.models import EventDetail, EventFormat, EventStatus
from events.policies import EVENT, UPCOMING
from opportunities.models import CloseReason, Opportunity, OpportunityStatus
from opportunities.policies import Manager

# What may still change once people can see the event: where to go and how many fit, not
# when or what.
EDITABLE_WHEN_PUBLISHED = frozenset({"venue", "online_url", "attendee_visibility", "capacity"})
SWEEP_BATCH = 500
S = EventStatus


def create_detail(opportunity: Opportunity, values: dict[str, Any]) -> EventDetail:
    return EventDetail.objects.create(opportunity=opportunity, **values)


def update_detail(detail: EventDetail, changes: dict[str, Any]) -> None:
    changes = dict(changes)
    if "capacity" in changes and detail.event_status:
        # People may be registering right now, so the number of places changes under the
        # same lock they take, and the waitlist moves up if room was made.
        registrations.set_capacity(detail.pk, changes.pop("capacity"))
        detail.refresh_from_db(fields=["capacity", "confirmed_count"])
    if not changes:
        return
    for field, value in changes.items():
        setattr(detail, field, value)
    detail.save(update_fields=list(changes))


def publication_errors(detail: EventDetail, opportunity: Opportunity) -> FieldErrors:
    """What is still missing before this event can be published, keyed like the request body."""
    errors: FieldErrors = {}
    now = timezone.now()
    if not detail.format:
        errors["event.format"] = ["Say whether the event is in person, online or both."]
    elif detail.format != EventFormat.ONLINE:
        if not detail.venue:
            errors["event.venue"] = ["Say where the event takes place."]
        if not opportunity.country_code:
            errors["country_code"] = ["Give the country the event takes place in."]
        if not opportunity.city:
            errors["city"] = ["Give the city the event takes place in."]
    if not detail.timezone:
        errors["event.timezone"] = ["Choose the time zone the times are in."]

    if detail.start_at is None:
        errors["event.start_at"] = ["Say when the event starts."]
    elif detail.start_at <= now:
        errors["event.start_at"] = ["The event must start in the future."]
    if detail.end_at is None:
        errors["event.end_at"] = ["Say when the event ends."]

    if detail.start_at is not None:
        if opportunity.deadline is not None and opportunity.deadline > detail.start_at:
            errors["deadline"] = ["Registration must close before the event starts."]
        opens = detail.registration_opens_at
        if opens is not None and opens >= (opportunity.deadline or detail.start_at):
            errors["event.registration_opens_at"] = [
                "Registration must open before it closes and before the event starts."
            ]
    return errors


def publish(detail: EventDetail, now: datetime) -> None:
    """Give a newly published event its first status. Registration is open straight away
    unless it was given a later opening time."""
    opens = detail.registration_opens_at
    detail.event_status = S.SCHEDULED if opens is not None and opens > now else S.REGISTRATION_OPEN
    detail.save(update_fields=["event_status"])


def cancel(detail: EventDetail, manager: Manager) -> None:
    """Call off an event that has not happened yet."""
    if detail.event_status not in UPCOMING:
        raise Conflict("This event is already over.", code="event_over")
    EVENT.apply(detail, S.CANCELLED, actor=manager)
    detail.save(update_fields=["event_status"])
    # Everyone registered is told, from a background task: there may be any number of them.
    from events.tasks import announce_cancellation  # imported here: tasks imports this module

    transaction.on_commit(partial(enqueue, announce_cancellation, str(detail.pk)))


# --- The periodic sweep -----------------------------------------------------------------


def _advance(due: Q, source: EventStatus, target: EventStatus, action: str) -> int:
    """Move every published event matching ``due`` from ``source`` to ``target``.

    Each event is moved under a lock on its opportunity (the same lock, taken in the same
    order, as a manager editing or cancelling it) by an update that repeats the conditions.
    So an event a manager changes at the same moment is left as they put it, and nothing is
    moved or audited twice.
    """
    published = Q(opportunity__status=OpportunityStatus.PUBLISHED)
    candidates = EventDetail.objects.filter(due, published, event_status=source)
    moved = 0
    for event_id in candidates.order_by("start_at").values_list("pk", flat=True)[:SWEEP_BATCH]:
        with transaction.atomic():
            opportunity = (
                Opportunity.objects.select_for_update()
                .filter(pk=event_id, status=OpportunityStatus.PUBLISHED)
                .first()
            )
            if opportunity is None:
                continue
            changed = EventDetail.objects.filter(due, pk=event_id, event_status=source).update(
                event_status=target
            )
            if not changed:
                continue
            if target == S.COMPLETED:
                now = timezone.now()
                Opportunity.objects.filter(pk=opportunity.pk).update(
                    status=OpportunityStatus.CLOSED,
                    closed_at=now,
                    close_reason=CloseReason.COMPLETED,
                    updated_at=now,
                )
            record(action=action, target=opportunity, organization_id=opportunity.organization_id)
            moved += 1
    return moved


def advance_states() -> dict[str, int]:
    """Open and close registration, and complete events, as their times pass.

    Safe to run at any time and any number of times. Registering checks the times itself,
    so a late run only delays a label, never lets anyone in early or late.
    """
    now = timezone.now()
    not_started = Q(start_at__gt=now)
    closing = Q(opportunity__deadline__lte=now) | Q(start_at__lte=now)
    opened = _advance(
        Q(registration_opens_at__lte=now) & not_started,
        S.SCHEDULED,
        S.REGISTRATION_OPEN,
        "event.registration_opened",
    )
    closed = _advance(
        closing, S.REGISTRATION_OPEN, S.REGISTRATION_CLOSED, "event.registration_closed"
    )
    completed = sum(
        _advance(Q(end_at__lte=now), source, S.COMPLETED, "event.completed")
        for source in sorted(UPCOMING)
    )
    return {"opened": opened, "closed": closed, "completed": completed}
