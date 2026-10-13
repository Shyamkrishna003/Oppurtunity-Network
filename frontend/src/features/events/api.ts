import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "../../services/http";
import { pagedQuery } from "../../services/pagination";
import { useSessionStatus } from "../auth/api";
import type {
  EventFormat,
  EventStatus,
  OpportunityStatus,
  RegistrationStatus,
} from "../opportunities/types";
import type { Person } from "../organizations/types";

export interface MyRegistration {
  id: string;
  status: RegistrationStatus;
  waitlist_position: number | null;
}

/** One person in an event's list, as its organizers see it. */
export interface Registration {
  id: string;
  status: RegistrationStatus;
  person: Person;
  waitlisted_at: string | null;
  created_at: string;
}

export interface RegistrationSummary {
  counts: Record<RegistrationStatus, number>;
  capacity: number | null;
}

export interface MyEvent {
  id: string;
  status: Exclude<RegistrationStatus, "CANCELLED">;
  created_at: string;
  event: {
    id: string;
    title: string;
    status: OpportunityStatus;
    event_status: EventStatus | "";
    format: EventFormat | "";
    start_at: string | null;
    end_at: string | null;
    timezone: string;
    venue: string;
    city: string;
    organization: { id: string; name: string } | null;
  };
}

export const eventKeys = {
  all: ["events"] as const,
  mine: ["events", "mine"] as const,
  attendees: (id: string) => ["events", id, "attendees"] as const,
  registrations: (id: string, status: string) => ["events", id, "registrations", status] as const,
  summary: (id: string) => ["events", id, "summary"] as const,
};

/** After anything changes who is coming: every list about events, and the event's own page
 *  (its count of places, and how the viewer stands). */
function useEventChanged() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: eventKeys.all });
    return queryClient.invalidateQueries({ queryKey: ["opportunities"] });
  };
}

function useEventAction<T>(path: (id: string) => string) {
  const changed = useEventChanged();
  return (id: string) =>
    // Awaited, so the button stays busy until the page shows the new state.
    http<T>(path(id), { method: "POST" }).finally(changed);
}

export function useRegister(eventId: string) {
  const post = useEventAction<MyRegistration>((id) => `/events/${id}/register/`);
  return useMutation({ mutationFn: () => post(eventId) });
}

export function useCancelRegistration(eventId: string) {
  const post = useEventAction<MyRegistration>((id) => `/events/${id}/cancel-registration/`);
  return useMutation({ mutationFn: () => post(eventId) });
}

export function useSetRegistrationOpen(eventId: string) {
  const changed = useEventChanged();
  return useMutation({
    mutationFn: (open: boolean) =>
      http<void>(`/events/${eventId}/${open ? "open" : "close"}-registration/`, {
        method: "POST",
      }).finally(changed),
  });
}

export function useRemoveRegistration(eventId: string) {
  const changed = useEventChanged();
  return useMutation({
    mutationFn: (registrationId: string) =>
      http<Registration>(`/events/${eventId}/registrations/${registrationId}/remove/`, {
        method: "POST",
      }).finally(changed),
  });
}

/** The people going. Fails with 403 when the organizers keep the list from this viewer. */
export function useAttendees(eventId: string, enabled: boolean) {
  const status = useSessionStatus();
  return useQuery({
    queryKey: [...eventKeys.attendees(eventId), status],
    queryFn: ({ signal }) => http<Person[]>(`/events/${eventId}/attendees/`, { signal }),
    enabled: enabled && status !== "unknown",
    retry: false,
  });
}

export function useEventRegistrations(eventId: string, status: RegistrationStatus | "") {
  const search = status ? `?status=${status}` : "";
  return useInfiniteQuery({
    queryKey: eventKeys.registrations(eventId, status),
    ...pagedQuery<Registration>(`/events/${eventId}/registrations/${search}`),
  });
}

export function useRegistrationSummary(eventId: string) {
  return useQuery({
    queryKey: eventKeys.summary(eventId),
    queryFn: ({ signal }) =>
      http<RegistrationSummary>(`/events/${eventId}/registrations/summary/`, { signal }),
  });
}

export function useMyEvents() {
  return useQuery({
    queryKey: eventKeys.mine,
    queryFn: ({ signal }) => http<MyEvent[]>("/users/me/event-registrations/", { signal }),
  });
}
