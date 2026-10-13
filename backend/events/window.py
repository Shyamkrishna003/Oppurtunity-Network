"""Opening and closing an event's registration by hand.

Normally the times do this by themselves. An organizer can close registration early, and
reopen it while that still makes sense.
"""

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from audit.services import record
from common.errors import Conflict
from events.models import EventStatus
from events.policies import EVENT
from opportunities.models import Opportunity, OpportunityStatus, OpportunityType
from opportunities.services import lock_opportunity, require_manager
from users.models import User

S = EventStatus


def _move(actor: User, opportunity_id: UUID, target: EventStatus, action: str) -> Opportunity:
    with transaction.atomic():
        opportunity = lock_opportunity(opportunity_id)
        manager = require_manager(actor, opportunity)
        if opportunity.type != OpportunityType.EVENT:
            raise Conflict("Only an event has registration.", code="not_an_event")
        if opportunity.status != OpportunityStatus.PUBLISHED:
            raise Conflict(
                "Registration can only be changed while the event is published.",
                code="event_not_published",
            )
        event = opportunity.event
        if target == S.REGISTRATION_OPEN:
            now = timezone.now()
            if event.start_at is not None and event.start_at <= now:
                raise Conflict("This event has already started.", code="event_started")
            if opportunity.deadline is not None and opportunity.deadline <= now:
                raise Conflict(
                    "The registration deadline has passed. Move it later to reopen registration.",
                    code="deadline_passed",
                )
        if EVENT.apply(event, target, actor=manager):
            event.save(update_fields=["event_status"])
            record(
                action=action,
                target=opportunity,
                actor=actor,
                organization_id=opportunity.organization_id,
            )
        return opportunity


def open_registration(*, actor: User, opportunity_id: UUID) -> Opportunity:
    """Open registration now: ahead of its opening time, or again after closing it."""
    return _move(actor, opportunity_id, S.REGISTRATION_OPEN, "event.registration_opened")


def close_registration(*, actor: User, opportunity_id: UUID) -> Opportunity:
    """Stop taking registrations. People already registered keep their places."""
    return _move(actor, opportunity_id, S.REGISTRATION_CLOSED, "event.registration_closed")
