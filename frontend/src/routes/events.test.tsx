import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EventDetail, FeedItem, OpportunityDetail } from "../features/opportunities/types";
import { makeSession, makeViewer } from "../test/fixtures";
import { apiError, json, mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const EVENT = "/api/v1/opportunities/ev-1/";
const page = <T,>(results: T[]) => json({ results, next: null, previous: null });

function eventDetail(overrides: Partial<EventDetail> = {}): EventDetail {
  return {
    event_status: "REGISTRATION_OPEN",
    format: "IN_PERSON",
    start_at: "2026-11-20T12:30:00Z",
    end_at: "2026-11-20T14:30:00Z",
    timezone: "Asia/Kolkata",
    venue: "Kerala Startup Mission",
    online_url: "",
    has_online_url: false,
    capacity: 40,
    confirmed_count: 12,
    registration_opens_at: null,
    attendee_visibility: "ATTENDEES",
    ...overrides,
  };
}

function opportunity(overrides: Partial<OpportunityDetail> = {}): OpportunityDetail {
  return {
    id: "ev-1",
    type: "EVENT",
    title: "Kochi Python Meetup",
    description: "Talks, pizza and people who build things.",
    status: "PUBLISHED",
    visibility: "PUBLIC",
    moderation_status: "VISIBLE",
    communities: [],
    work_mode: "ONSITE",
    country_code: "IN",
    region: "",
    city: "Kochi",
    deadline: "2026-11-19T12:30:00Z",
    published_at: "2026-10-01T00:00:00Z",
    closed_at: null,
    close_reason: "",
    created_at: "2026-09-30T00:00:00Z",
    organization: null,
    posted_by: { id: "u-2", display_name: "Grace Hopper", headline: "", avatar_url: null },
    skills: [],
    job: null,
    event: eventDetail(),
    viewer: makeViewer(),
    ...overrides,
  };
}

const asManager = (overrides: Partial<OpportunityDetail> = {}) =>
  opportunity({ viewer: makeViewer({ can_manage: true, editable_fields: [] }), ...overrides });

beforeEach(() => vi.spyOn(window, "confirm").mockReturnValue(true));
afterEach(() => vi.unstubAllGlobals());

describe("event page", () => {
  it("shows when, where and how full it is, in the event's own time zone", async () => {
    mockApi({ [`GET ${EVENT}`]: () => json(opportunity()) });
    renderApp("/opportunities/ev-1");

    expect(await screen.findByRole("heading", { name: "Kochi Python Meetup" })).toBeVisible();
    const about = screen.getByRole("region", { name: "About the event" });
    // 12:30 UTC is 6 in the evening in Kochi, wherever the reader is.
    expect(within(about).getByText(/Nov 20, 2026, 6:00\sPM – 8:00\sPM/)).toBeVisible();
    expect(within(about).getByText("Kerala Startup Mission, Kochi, IN")).toBeVisible();
    expect(within(about).getByText("12 of 40 taken")).toBeVisible();
    expect(within(about).getByText("Registration open")).toBeVisible();
    expect(within(about).getByText("Register by")).toBeVisible();
    // Nothing that belongs to a job.
    expect(screen.queryByText("Openings")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Apply" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Manage" })).toBeNull();
  });

  it("keeps the joining link for the people running it", async () => {
    const online = eventDetail({ format: "ONLINE", venue: "", has_online_url: true });
    mockApi({ [`GET ${EVENT}`]: () => json(opportunity({ event: online, work_mode: "REMOTE" })) });
    renderApp("/opportunities/ev-1");

    expect(await screen.findByText("The link to join is shared with attendees.")).toBeVisible();
    expect(screen.queryByRole("link", { name: /meet\.example/ })).toBeNull();

    cleanup();
    vi.unstubAllGlobals();
    const mine = { ...online, online_url: "https://meet.example.com/kochi" };
    mockApi({
      [`GET ${EVENT}`]: () => json(asManager({ event: mine })),
      [`GET ${EVENT}communities/`]: () => json([]),
      [`GET ${EVENT}communities/options/`]: () => json([]),
    });
    renderApp("/opportunities/ev-1", makeSession());
    const link = await screen.findByRole("link", { name: "https://meet.example.com/kochi" });
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("says so when an event is cancelled or over", async () => {
    mockApi({
      [`GET ${EVENT}`]: () =>
        json(
          opportunity({
            status: "CLOSED",
            close_reason: "CANCELLED",
            event: eventDetail({ event_status: "CANCELLED" }),
          }),
        ),
    });
    renderApp("/opportunities/ev-1");
    expect(await screen.findByText("This event has been cancelled.")).toBeVisible();
    expect(screen.queryByText(/no longer takes applications/)).toBeNull();
  });
});

describe("running an event", () => {
  const routes = (detail: OpportunityDetail) => ({
    [`GET ${EVENT}`]: () => json(detail),
    [`GET ${EVENT}communities/`]: () => json([]),
    [`GET ${EVENT}communities/options/`]: () => json([]),
  });

  it("cancels after confirmation, with no reason to choose", async () => {
    const cancelled = asManager({
      status: "CLOSED",
      close_reason: "CANCELLED",
      event: eventDetail({ event_status: "CANCELLED" }),
    });
    const open = asManager({
      viewer: makeViewer({ can_manage: true, editable_fields: ["description"] }),
    });
    // The page asks again after the change, so the server answers with what it now holds.
    let current = open;
    const api = mockApi({
      ...routes(open),
      [`GET ${EVENT}`]: () => json(current),
      [`POST ${EVENT}close/`]: () => {
        current = cancelled;
        return json(cancelled);
      },
    });
    renderApp("/opportunities/ev-1", makeSession());
    const user = userEvent.setup();

    const manage = await screen.findByRole("region", { name: "Manage" });
    expect(within(manage).queryByLabelText("Reason for closing")).toBeNull();
    // Applications are a job's business.
    expect(within(manage).queryByRole("link", { name: "View applications" })).toBeNull();
    await user.click(within(manage).getByRole("button", { name: "Cancel event" }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("Cancel this event?"));
    await waitFor(() =>
      expect(api.last(`POST ${EVENT}close/`)?.body).toEqual({ reason: "CANCELLED" }),
    );
    expect(await screen.findByText("This event has been cancelled.")).toBeVisible();
  });

  it("does not cancel when the confirmation is declined", async () => {
    vi.mocked(window.confirm).mockReturnValue(false);
    const api = mockApi({
      ...routes(
        asManager({ viewer: makeViewer({ can_manage: true, editable_fields: ["description"] }) }),
      ),
    });
    renderApp("/opportunities/ev-1", makeSession());

    await userEvent.setup().click(await screen.findByRole("button", { name: "Cancel event" }));

    expect(api.count(`POST ${EVENT}close/`)).toBe(0);
  });

  it("names what an event still needs before it can be published", async () => {
    mockApi({
      ...routes(
        asManager({
          status: "DRAFT",
          published_at: null,
          event: eventDetail({ event_status: "", start_at: null, end_at: null }),
          viewer: makeViewer({ can_manage: true, editable_fields: null }),
        }),
      ),
      [`POST ${EVENT}publish/`]: () =>
        apiError(422, "incomplete", "Complete these details before publishing.", {
          "event.start_at": ["Say when the event starts."],
          "event.venue": ["Say where the event takes place."],
        }),
    });
    renderApp("/opportunities/ev-1", makeSession());

    await userEvent.setup().click(await screen.findByRole("button", { name: "Publish" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Starts:")).toBeVisible();
    expect(within(alert).getByText("Venue:")).toBeVisible();
  });
});

describe("hosting an event", () => {
  it("saves a draft with its times read in the chosen time zone", async () => {
    const api = mockApi({
      "GET /api/v1/users/me/organizations/": () => page([]),
      "POST /api/v1/opportunities/": () => json(opportunity({ status: "DRAFT" }), 201),
      [`GET ${EVENT}`]: () => json(opportunity({ status: "DRAFT" })),
    });
    const router = renderApp("/opportunities/new?type=event", makeSession());
    const user = userEvent.setup();

    expect(await screen.findByRole("heading", { name: "Host an event" })).toBeVisible();
    expect(screen.getByRole("link", { name: "An event" })).toHaveAttribute("aria-current", "page");
    // Fields that only a job has are not asked for.
    expect(screen.queryByLabelText("Employment type")).toBeNull();

    await user.type(screen.getByLabelText("Event name"), "Kochi Python Meetup");
    await user.type(screen.getByLabelText("Description"), "Talks and pizza.");
    await user.selectOptions(screen.getByLabelText("Format"), "IN_PERSON");
    await user.selectOptions(screen.getByLabelText("Time zone"), "Europe/London");
    fireEvent.change(screen.getByLabelText("Starts"), { target: { value: "2026-11-20T18:00" } });
    fireEvent.change(screen.getByLabelText("Ends"), { target: { value: "2026-11-20T20:00" } });
    await user.type(screen.getByLabelText("Venue"), "The Guildhall");
    await user.type(screen.getByLabelText("City"), "London");
    await user.type(screen.getByLabelText("Country code"), "GB");
    await user.type(screen.getByLabelText("Places (optional)"), "40");
    // An in-person event has no joining link to ask for.
    expect(screen.queryByLabelText("Link to join online (optional)")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/opportunities/ev-1"));
    expect(api.last("POST /api/v1/opportunities/")?.body).toEqual({
      type: "EVENT",
      organization_id: null,
      title: "Kochi Python Meetup",
      description: "Talks and pizza.",
      visibility: "PUBLIC",
      work_mode: "",
      city: "London",
      region: "",
      country_code: "GB",
      deadline: null,
      skill_ids: [],
      event: {
        format: "IN_PERSON",
        // London is on GMT in November, so the clock time is the UTC time.
        start_at: "2026-11-20T18:00:00.000Z",
        end_at: "2026-11-20T20:00:00.000Z",
        timezone: "Europe/London",
        venue: "The Guildhall",
        online_url: "",
        capacity: 40,
        registration_opens_at: null,
        attendee_visibility: "ATTENDEES",
      },
    });
  });

  it("checks the times before calling the server", async () => {
    const api = mockApi({ "GET /api/v1/users/me/organizations/": () => page([]) });
    renderApp("/opportunities/new?type=event", makeSession());
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Event name"), "Meetup");
    fireEvent.change(screen.getByLabelText("Starts"), { target: { value: "2026-11-20T18:00" } });
    fireEvent.change(screen.getByLabelText("Ends"), { target: { value: "2026-11-20T17:00" } });
    await user.click(screen.getByRole("button", { name: "Save draft" }));

    expect(await screen.findByText("The event must end after it starts.")).toBeVisible();
    expect(api.count("POST /api/v1/opportunities/")).toBe(0);
  });

  it("opens a published event with only the safe fields unlocked", async () => {
    mockApi({
      [`GET ${EVENT}`]: () =>
        json(
          asManager({
            viewer: makeViewer({ can_manage: true, editable_fields: ["deadline", "description"] }),
          }),
        ),
    });
    renderApp("/opportunities/ev-1/edit", makeSession());

    expect(await screen.findByRole("heading", { name: "Edit event" })).toBeVisible();
    expect(screen.getByLabelText("Event name")).toBeDisabled();
    expect(screen.getByLabelText("Starts")).toBeDisabled();
    expect(screen.getByLabelText("Format")).toBeDisabled();
    expect(screen.getByLabelText("Venue")).toBeEnabled();
    expect(screen.getByLabelText("Description")).toBeEnabled();
    // Shown as the clock reads in Kochi.
    expect(screen.getByLabelText("Starts")).toHaveValue("2026-11-20T18:00");
  });
});

describe("events in the feed", () => {
  it("marks events among jobs and filters by type through the address", async () => {
    const item: FeedItem = { ...opportunity(), is_saved: false, match: null };
    const api = mockApi({ "GET /api/v1/opportunities/": () => page([item]) });
    const router = renderApp("/opportunities");
    const user = userEvent.setup();

    const card = (await screen.findByRole("link", { name: "Kochi Python Meetup" })).closest("li")!;
    expect(within(card).getByText("Event")).toBeVisible();
    expect(within(card).getByText(/6:00\sPM – 8:00\sPM/)).toBeVisible();
    expect(card).toHaveTextContent("Register by");

    await user.click(screen.getByText("Filters"));
    await user.selectOptions(screen.getByLabelText("Type"), "EVENT");

    await waitFor(() => expect(router.state.location.search).toBe("?type=EVENT"));
    expect(api.last("GET /api/v1/opportunities/")?.url.searchParams.get("type")).toBe("EVENT");
  });
});
