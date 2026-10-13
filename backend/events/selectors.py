"""Read queries for events and their registrations."""

from dataclasses import dataclass
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.db.models import Count, Exists, OuterRef, Q, QuerySet
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from events import policies
from events.models import EventDetail, EventRegistration, RegistrationStatus
from opportunities import policies as opportunity_policies
from opportunities import selectors as opportunities
from opportunities.models import ModerationStatus, Opportunity, OpportunityStatus, OpportunityType
from users.models import User, UserBlock
from users.selectors import is_blocked_either_way

Viewer = User | AnonymousUser
R = RegistrationStatus


def get_event(viewer: Viewer, opportunity_id: UUID) -> Opportunity:
    """The event if the viewer may see it. Something that is not an event, a draft and one
    that does not exist all look the same from outside."""
    opportunity = opportunities.get_opportunity(viewer, opportunity_id)
    if opportunity.type != OpportunityType.EVENT:
        raise Http404
    return opportunity


def is_manager(viewer: Viewer, opportunity: Opportunity) -> bool:
    return viewer.is_authenticated and opportunity_policies.can_manage(
        viewer, opportunity, opportunities.get_membership(viewer, opportunity.organization_id)
    )


def get_managed_event(user: User, opportunity_id: UUID) -> Opportunity:
    """The event, for someone about to manage who is coming. 404 if they cannot see it; 403
    if they can but do not manage it."""
    opportunity = get_event(user, opportunity_id)
    if not is_manager(user, opportunity):
        raise PermissionDenied()
    return opportunity


def registration_of(viewer: Viewer, opportunity: Opportunity) -> EventRegistration | None:
    if not viewer.is_authenticated:
        return None
    return EventRegistration.objects.filter(event_id=opportunity.pk, user=viewer).first()


def waitlist_position(registration: EventRegistration) -> int | None:
    """Where in the queue someone is, counting from 1. None unless they are waiting."""
    if registration.status != R.WAITLISTED or registration.waitlisted_at is None:
        return None
    ahead = Q(waitlisted_at__lt=registration.waitlisted_at) | Q(
        waitlisted_at=registration.waitlisted_at, pk__lt=registration.pk
    )
    return (
        EventRegistration.objects.filter(ahead, event_id=registration.event_id, status=R.WAITLISTED)
    ).count() + 1


def can_register(viewer: Viewer, opportunity: Opportunity) -> bool:
    """Whether registering would be accepted right now. The service decides for real, under
    a lock; this is for showing or hiding the button."""
    if not viewer.is_authenticated or opportunity.type != OpportunityType.EVENT:
        return False
    if (
        opportunity.status != OpportunityStatus.PUBLISHED
        or opportunity.moderation_status != ModerationStatus.VISIBLE
        or not policies.registration_is_open(
            opportunity.event, opportunity.deadline, timezone.now()
        )
    ):
        return False
    # A personal event whose host and this person have blocked one another reads as closed.
    return opportunity.organization_id is not None or not is_blocked_either_way(
        viewer, opportunity.creator
    )


@dataclass(frozen=True)
class Attending:
    """How the viewer stands with an event, for the page that shows it."""

    registration: EventRegistration | None
    waitlist_position: int | None
    can_register: bool
    # Holds a place: sees the joining link, and the attendee list when it is for attendees.
    is_going: bool


def attending_state(viewer: Viewer, opportunity: Opportunity) -> Attending:
    if opportunity.type != OpportunityType.EVENT:
        return Attending(None, None, False, False)
    registration = registration_of(viewer, opportunity)
    active = registration is not None and registration.status in policies.ACTIVE
    return Attending(
        registration=registration,
        waitlist_position=waitlist_position(registration) if registration else None,
        can_register=not active and can_register(viewer, opportunity),
        is_going=registration is not None and registration.status == R.CONFIRMED,
    )


def list_registrations(opportunity: Opportunity, status: str = "") -> QuerySet[EventRegistration]:
    """Everyone who ever registered, for the organizers, optionally in one status only.
    The view orders them by when they first signed up."""
    registrations = EventRegistration.objects.filter(event_id=opportunity.pk)
    if status:
        registrations = registrations.filter(status=status)
    return registrations.select_related("user__profile")


def registration_counts(opportunity: Opportunity) -> dict[str, int]:
    counted = dict(
        EventRegistration.objects.filter(event_id=opportunity.pk)
        .values_list("status")
        .annotate(total=Count("id"))
    )
    return {status: counted.get(status, 0) for status in R.values}


def checked_in_count(opportunity: Opportunity) -> int:
    return EventRegistration.objects.filter(
        event_id=opportunity.pk, checked_in_at__isnull=False
    ).count()


def list_attendees(viewer: Viewer, opportunity: Opportunity) -> QuerySet[User]:
    """The people going, as far as the viewer may see them.

    Whether the list is shown at all is the organizer's choice. Within it, people the viewer
    has blocked, or who blocked the viewer, are left out, as they are everywhere else.
    """
    event: EventDetail = opportunity.event
    going = registration_of(viewer, opportunity)
    allowed = policies.can_see_attendees(
        event,
        is_manager=is_manager(viewer, opportunity),
        is_attending=going is not None and going.status == R.CONFIRMED,
    )
    if not allowed:
        raise PermissionDenied()
    attendees = User.objects.filter(
        event_registrations__event_id=opportunity.pk,
        event_registrations__status=R.CONFIRMED,
        is_active=True,
    ).select_related("profile")
    if viewer.is_authenticated:
        blocked = UserBlock.objects.filter(
            Q(blocker=viewer, blocked=OuterRef("pk")) | Q(blocker=OuterRef("pk"), blocked=viewer)
        )
        attendees = attendees.exclude(Exists(blocked))
    return attendees.order_by("event_registrations__created_at", "pk")


def list_mine(user: User) -> QuerySet[EventRegistration]:
    """The events the user is going to or waiting for, soonest first, then past ones."""
    return (
        EventRegistration.objects.filter(user=user, status__in=policies.ACTIVE)
        .select_related("event__opportunity__organization", "event__opportunity__creator__profile")
        .order_by("event__start_at", "pk")
    )
