from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from events.models import EventDetail, EventRegistration
from events.policies import WORK_MODE_FOR
from opportunities import search
from opportunities.models import Opportunity
from users.tests.factories import UserFactory

_counter = iter(range(1, 1_000_000))


def make_event(*, status="DRAFT", event=None, **fields) -> Opportunity:
    """An event opportunity in the given state, complete enough to publish unless told
    otherwise: in person, in Kochi, a week from now.

    Rows are written directly (not through the services), so tests can start from any state.
    """
    now = timezone.now()
    detail = {
        "format": "IN_PERSON",
        "start_at": now + timedelta(days=7),
        "end_at": now + timedelta(days=7, hours=2),
        "timezone": "Asia/Kolkata",
        "venue": "Kerala Startup Mission, Kalamassery",
        **(event or {}),
    }
    if status != "DRAFT":
        fields.setdefault("published_at", now - timedelta(days=1))
        detail.setdefault("event_status", "REGISTRATION_OPEN")
    if status in ("CLOSED", "ARCHIVED"):
        fields.setdefault("closed_at", now)
        fields.setdefault("close_reason", "CANCELLED")
        detail["event_status"] = (
            "COMPLETED" if fields["close_reason"] == "COMPLETED" else "CANCELLED"
        )
    if "creator" not in fields:
        fields["creator"] = UserFactory()
    fields.setdefault("title", f"Kochi Python Meetup {next(_counter)}")
    fields.setdefault("description", "Talks, pizza and people who build things.")
    fields.setdefault("work_mode", WORK_MODE_FOR.get(detail["format"], ""))
    if detail["format"] != "ONLINE":
        fields.setdefault("city", "Kochi")
        fields.setdefault("country_code", "IN")

    opportunity = Opportunity.objects.create(type="EVENT", status=status, **fields)
    EventDetail.objects.create(opportunity=opportunity, **detail)
    search.reindex(opportunity)
    return opportunity


def add_registration(event, user=None, status="CONFIRMED") -> EventRegistration:
    """A registration written directly, keeping the event's count of places in step.

    Waitlisted ones queue in the order they are added.
    """
    registration = EventRegistration.objects.create(
        event_id=event.pk,
        user=user or UserFactory.create(),
        status=status,
        waitlisted_at=timezone.now() if status == "WAITLISTED" else None,
    )
    if status == "CONFIRMED":
        EventDetail.objects.filter(pk=event.pk).update(confirmed_count=F("confirmed_count") + 1)
    return registration
