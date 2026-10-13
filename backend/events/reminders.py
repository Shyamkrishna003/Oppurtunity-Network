"""Reminders to the people going to an event: one the day before, one an hour before.

Run by a periodic sweep. Nothing here depends on the sweep being punctual or running once:
each person's reminder is keyed, so it is created at most once however often this runs, and
an event is only marked as reminded after everyone has been.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone

from events.models import EventDetail, EventRegistration, RegistrationStatus
from events.policies import UPCOMING
from notifications.models import NotificationType
from notifications.services import notify
from opportunities.models import OpportunityStatus

EVENTS_PER_RUN = 50
CHUNK = 500


@dataclass(frozen=True)
class Lead:
    """One kind of reminder: how long before the start, and where it is ticked off."""

    key: str
    before: timedelta
    sent_field: str


DAY_BEFORE = Lead("24h", timedelta(hours=24), "reminder_24h_sent_at")
HOUR_BEFORE = Lead("1h", timedelta(hours=1), "reminder_1h_sent_at")


def starts_text(event: EventDetail) -> str:
    """When the event starts, as a clock in its own time zone reads: 'Fri 23 Oct, 18:00'."""
    assert event.start_at is not None
    try:
        zone = ZoneInfo(event.timezone)
    except ZoneInfoNotFoundError, ValueError:
        zone = ZoneInfo("UTC")
    local = event.start_at.astimezone(zone)
    return f"{local:%a} {local.day} {local:%b}, {local:%H:%M}"


def _remind(event: EventDetail, lead: Lead) -> int:
    opportunity = event.opportunity
    payload = {
        "opportunity_id": str(opportunity.pk),
        "opportunity_title": opportunity.title,
        "lead": lead.key,
        "starts": starts_text(event),
        "timezone": event.timezone,
        "venue": event.venue,
    }
    reminded = 0
    going = (
        EventRegistration.objects.filter(event=event, status=RegistrationStatus.CONFIRMED)
        .select_related("user")
        .order_by("pk")
    )
    for registration in going.iterator(chunk_size=CHUNK):
        # Each in its own transaction, so one failure does not undo the others and each
        # email is queued as soon as its notification is saved.
        with transaction.atomic():
            notice = notify(
                recipient=registration.user,
                type=NotificationType.EVENT_REMINDER,
                target=opportunity,
                payload=payload,
                dedupe_key=f"event-reminder:{event.pk}:{lead.key}",
            )
        reminded += notice is not None
    # Ticked off last: if this run dies halfway, the next one finishes the job, and the
    # keys above keep anyone from being reminded twice.
    EventDetail.objects.filter(pk=event.pk).update(**{lead.sent_field: timezone.now()})
    return reminded


def _due(lead: Lead, now: datetime, after: timedelta) -> list[EventDetail]:
    """Published events still to come that start within the lead time (but not within
    ``after``, which belongs to the next reminder) and have not had this reminder."""
    return list(
        EventDetail.objects.filter(
            opportunity__status=OpportunityStatus.PUBLISHED,
            event_status__in=UPCOMING,
            start_at__gt=now + after,
            start_at__lte=now + lead.before,
            **{f"{lead.sent_field}__isnull": True},
        )
        .select_related("opportunity")
        .order_by("start_at")[:EVENTS_PER_RUN]
    )


def send_due() -> dict[str, int]:
    """Send every reminder that is due. Returns how many people were reminded, per kind."""
    now = timezone.now()
    return {
        # An event less than an hour away gets the hour reminder only.
        DAY_BEFORE.key: sum(
            _remind(event, DAY_BEFORE) for event in _due(DAY_BEFORE, now, HOUR_BEFORE.before)
        ),
        HOUR_BEFORE.key: sum(
            _remind(event, HOUR_BEFORE) for event in _due(HOUR_BEFORE, now, timedelta(0))
        ),
    }
