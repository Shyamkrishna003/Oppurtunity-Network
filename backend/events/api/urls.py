from django.urls import path

from events.api import views

urlpatterns = [
    # An event's ID is its opportunity's ID.
    path(
        "events/<uuid:opportunity_id>/register/",
        views.RegisterView.as_view(),
        name="event-register",
    ),
    path(
        "events/<uuid:opportunity_id>/cancel-registration/",
        views.CancelRegistrationView.as_view(),
        name="event-cancel-registration",
    ),
    path(
        "events/<uuid:opportunity_id>/my-registration/",
        views.MyRegistrationView.as_view(),
        name="event-my-registration",
    ),
    path(
        "events/<uuid:opportunity_id>/registrations/",
        views.EventRegistrationsView.as_view(),
        name="event-registrations",
    ),
    path(
        "events/<uuid:opportunity_id>/registrations/summary/",
        views.EventRegistrationsSummaryView.as_view(),
        name="event-registrations-summary",
    ),
    path(
        "events/<uuid:opportunity_id>/registrations/<uuid:registration_id>/remove/",
        views.RemoveRegistrationView.as_view(),
        name="event-registration-remove",
    ),
    path(
        "events/<uuid:opportunity_id>/attendees/",
        views.AttendeesView.as_view(),
        name="event-attendees",
    ),
    path(
        "events/<uuid:opportunity_id>/open-registration/",
        views.OpenRegistrationView.as_view(),
        name="event-open-registration",
    ),
    path(
        "events/<uuid:opportunity_id>/close-registration/",
        views.CloseRegistrationView.as_view(),
        name="event-close-registration",
    ),
    path(
        "users/me/event-registrations/",
        views.MyEventRegistrationsView.as_view(),
        name="user-me-event-registrations",
    ),
]
