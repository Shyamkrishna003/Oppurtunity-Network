from django.db import models


class EventStatus(models.TextChoices):
    """Where an event is with registration and whether it happened. Separate from the
    opportunity's publication status: an event past its registration deadline is still a
    published opportunity until it is over."""

    SCHEDULED = "SCHEDULED", "Registration not open yet"
    REGISTRATION_OPEN = "REGISTRATION_OPEN", "Registration open"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED", "Registration closed"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class EventFormat(models.TextChoices):
    IN_PERSON = "IN_PERSON", "In person"
    ONLINE = "ONLINE", "Online"
    HYBRID = "HYBRID", "In person and online"


class AttendeeVisibility(models.TextChoices):
    PUBLIC = "PUBLIC", "Anyone who can see the event"
    ATTENDEES = "ATTENDEES", "People who are going"
    HIDDEN = "HIDDEN", "Only the organizers"


class EventDetail(models.Model):
    """The fields only an event has. Exists exactly when ``opportunity.type`` is EVENT; both
    rows are created together by the opportunity service.

    The opportunity's ``deadline`` is when registration closes; it never expires the event.
    Times are stored in UTC; ``timezone`` is the place the event happens in, for showing
    them and for sending reminders at a sensible local hour.
    """

    opportunity = models.OneToOneField(
        "opportunities.Opportunity",
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="event",
    )
    # Blank until the event is published.
    event_status = models.CharField(max_length=20, choices=EventStatus.choices, blank=True)
    # Blank while drafting; required to publish.
    format = models.CharField(max_length=10, choices=EventFormat.choices, blank=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=64, blank=True)
    venue = models.CharField(max_length=200, blank=True)
    # Where to join online. Not for everyone who can see the event: see the serializer.
    online_url = models.URLField(blank=True)
    # No value means there is no limit.
    capacity = models.PositiveIntegerField(null=True, blank=True)
    # Only ever changed under a lock on this row, together with the registrations it counts.
    confirmed_count = models.PositiveIntegerField(default=0)
    # No value means registration opens as soon as the event is published.
    registration_opens_at = models.DateTimeField(null=True, blank=True)
    attendee_visibility = models.CharField(
        max_length=10, choices=AttendeeVisibility.choices, default=AttendeeVisibility.ATTENDEES
    )
    reminder_24h_sent_at = models.DateTimeField(null=True, blank=True)
    reminder_1h_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(event_status__in=["", *EventStatus.values]),
                name="events_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(format__in=["", *EventFormat.values]),
                name="events_format_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(attendee_visibility__in=AttendeeVisibility.values),
                name="events_attendee_visibility_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(start_at__isnull=True)
                | models.Q(end_at__isnull=True)
                | models.Q(end_at__gt=models.F("start_at")),
                name="events_ends_after_it_starts",
            ),
            models.CheckConstraint(
                condition=models.Q(capacity__isnull=True) | models.Q(capacity__gte=1),
                name="events_capacity_positive",
            ),
            # The last line of defence against overbooking; the service is the first.
            models.CheckConstraint(
                condition=models.Q(capacity__isnull=True)
                | models.Q(confirmed_count__lte=models.F("capacity")),
                name="events_not_overbooked",
            ),
        ]
        indexes = [
            models.Index(fields=["start_at"], name="events_start"),
            # The sweeps that open and close registration and complete events.
            models.Index(fields=["event_status", "start_at"], name="events_status_start"),
        ]

    def __str__(self) -> str:
        return f"event {self.pk}"
