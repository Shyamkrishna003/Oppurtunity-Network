from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.pagination import CursorPagination
from common.throttles import ScopedThrottle
from events import checkin, registrations, selectors, window
from events.api import serializers
from events.models import EventRegistration, RegistrationStatus
from organizations.api.serializers import PersonSerializer
from users.api.utils import current_user
from users.models import User
from users.permissions import IsVerified


class RegisterView(APIView):
    permission_classes = [IsVerified]
    throttle_classes = [ScopedThrottle]
    throttle_scope = "event_register"

    @extend_schema(
        request=None,
        responses={
            201: serializers.MyRegistrationSerializer,
            200: serializers.MyRegistrationSerializer,
        },
    )
    def post(self, request: Request, opportunity_id: UUID) -> Response:
        """Take a place at an event, or join the waitlist if it is full.

        Answers 201 with ``status`` CONFIRMED or WAITLISTED (and the position in the queue).
        If the caller is already going or waiting, answers 200 with that registration.
        Answers 409 ``registration_closed`` when registration is not open.
        """
        registration, changed = registrations.register(
            user=current_user(request), opportunity_id=opportunity_id
        )
        return Response(
            serializers.MyRegistrationSerializer(registration).data,
            status=status.HTTP_201_CREATED if changed else status.HTTP_200_OK,
        )


class CancelRegistrationView(APIView):
    @extend_schema(request=None, responses=serializers.MyRegistrationSerializer)
    def post(self, request: Request, opportunity_id: UUID) -> Response:
        """Give up the caller's place, or their place in the queue. The next person waiting
        gets the place at once."""
        selectors.get_event(request.user, opportunity_id)
        registration = registrations.cancel_registration(
            user=current_user(request), opportunity_id=opportunity_id
        )
        return Response(serializers.MyRegistrationSerializer(registration).data)


class MyRegistrationView(APIView):
    @extend_schema(responses=serializers.MyRegistrationSerializer)
    def get(self, request: Request, opportunity_id: UUID) -> Response:
        """The caller's registration for this event; 404 if they never registered."""
        opportunity = selectors.get_event(request.user, opportunity_id)
        registration = selectors.registration_of(request.user, opportunity)
        if registration is None:
            raise NotFound()
        return Response(serializers.MyRegistrationSerializer(registration).data)


def _requested_status(request: Request) -> str:
    requested = request.query_params.get("status", "")
    if requested and requested not in RegistrationStatus.values:
        raise ValidationError(
            {"status": [f"Choose one of: {', '.join(RegistrationStatus.values)}."]}
        )
    return requested


class _OldestFirst(CursorPagination):
    """The order people first signed up in. For the waitlist this is the queue, except for
    someone who cancelled and came back: they are listed early but queue from their return."""

    ordering = ("created_at", "id")


class EventRegistrationsView(generics.ListAPIView[EventRegistration]):
    """Everyone who registered for an event, for the people who run it."""

    serializer_class = serializers.RegistrationSerializer
    pagination_class = _OldestFirst

    def get_queryset(self) -> QuerySet[EventRegistration]:
        if getattr(self, "swagger_fake_view", False):
            return EventRegistration.objects.none()
        event = selectors.get_managed_event(
            current_user(self.request), self.kwargs["opportunity_id"]
        )
        return selectors.list_registrations(event, _requested_status(self.request))

    @extend_schema(parameters=[OpenApiParameter("status", str, enum=RegistrationStatus.values)])
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)


class EventRegistrationsSummaryView(APIView):
    @extend_schema(responses=serializers.RegistrationSummarySerializer)
    def get(self, request: Request, opportunity_id: UUID) -> Response:
        """How many people are going, waiting and cancelled, and how many places there are."""
        event = selectors.get_managed_event(current_user(request), opportunity_id)
        return Response(
            {
                "counts": selectors.registration_counts(event),
                "capacity": event.event.capacity,
                "checked_in": selectors.checked_in_count(event),
                "checkin_open": checkin.is_open(event.event, timezone.now()),
            }
        )


class CheckInView(APIView):
    throttle_classes = [ScopedThrottle]
    throttle_scope = "event_checkin"

    @extend_schema(
        request=serializers.CheckInRequestSerializer, responses=serializers.CheckInSerializer
    )
    def post(self, request: Request, opportunity_id: UUID) -> Response:
        """Check someone in from the code they show, as an organizer of the event.

        Answers 200 with who it was. A code that was already used answers 409
        ``already_checked_in``, with the time of the first scan in ``errors.checked_in_at``.
        A code that is forged, altered, for another event or no longer current answers 422
        ``invalid_code``; outside the check-in window, 422 ``checkin_closed``.

        This is the only way a registration becomes checked in: nothing accepts a flag.
        """
        serializer = serializers.CheckInRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        checked = checkin.check_in(
            actor=current_user(request),
            opportunity_id=opportunity_id,
            code=serializer.validated_data["code"],
        )
        if not checked.newly:
            raise checkin.already(checked)
        registration = checked.registration
        return Response(
            serializers.CheckInSerializer(
                {"person": registration.user, "checked_in_at": registration.checked_in_at}
            ).data
        )


class RemoveRegistrationView(APIView):
    @extend_schema(request=None, responses=serializers.RegistrationSerializer)
    def post(self, request: Request, opportunity_id: UUID, registration_id: UUID) -> Response:
        """Cancel someone's registration as an organizer. They are told, and the next person
        waiting gets the place."""
        registration = registrations.remove(
            actor=current_user(request),
            opportunity_id=opportunity_id,
            registration_id=registration_id,
        )
        return Response(serializers.RegistrationSerializer(registration).data)


class AttendeesView(generics.ListAPIView[User]):
    """The people going to an event, if the organizers let the caller see them: everyone,
    only people who are going themselves, or nobody but the organizers (403)."""

    permission_classes = [AllowAny]
    serializer_class = PersonSerializer
    pagination_class = None

    # A list of names is short to send and awkward to page by "who signed up first", so it
    # is capped instead: the organizers' own list pages through everyone.
    MAX_SHOWN = 200

    def get_queryset(self) -> QuerySet[User]:
        if getattr(self, "swagger_fake_view", False):
            return User.objects.none()
        opportunity = selectors.get_event(self.request.user, self.kwargs["opportunity_id"])
        return selectors.list_attendees(self.request.user, opportunity)[: self.MAX_SHOWN]


class _WindowView(APIView):
    change = staticmethod(window.open_registration)

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, opportunity_id: UUID) -> Response:
        selectors.get_event(request.user, opportunity_id)
        self.change(actor=current_user(request), opportunity_id=opportunity_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class OpenRegistrationView(_WindowView):
    """Open registration now: ahead of its opening time, or again after closing it."""


class CloseRegistrationView(_WindowView):
    """Stop taking registrations. People already registered keep their places."""

    change = staticmethod(window.close_registration)


class MyEventRegistrationsView(generics.ListAPIView[EventRegistration]):
    """The events the caller is going to or waiting for, soonest first."""

    serializer_class = serializers.MyEventRegistrationSerializer
    pagination_class = None
    MAX_SHOWN = 100

    def get_queryset(self) -> QuerySet[EventRegistration]:
        if getattr(self, "swagger_fake_view", False):
            return EventRegistration.objects.none()
        return selectors.list_mine(current_user(self.request))[: self.MAX_SHOWN]
