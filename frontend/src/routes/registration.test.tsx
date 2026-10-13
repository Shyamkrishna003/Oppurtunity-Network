import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MyEvent, Registration, RegistrationSummary } from "../features/events/api";
import type { EventDetail, OpportunityDetail } from "../features/opportunities/types";
import { makeMe, makeSession, makeViewer } from "../test/fixtures";
import { apiError, json, mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const PAGE = "/api/v1/opportunities/ev-1/";
const EVENTS = "/api/v1/events/ev-1/";
const page = <T,>(results: T[]) => json({ results, next: null, previous: null });
type Viewer = OpportunityDetail["viewer"];

function event(overrides: Partial<EventDetail> = {}, viewer: Partial<Viewer> = {}) {
  const detail: OpportunityDetail = {
    id: "ev-1",
    type: "EVENT",
    title: "Kochi Python Meetup",
    description: "Talks and pizza.",
    status: "PUBLISHED",
    visibility: "PUBLIC",
    moderation_status: "VISIBLE",
    communities: [],
    work_mode: "ONSITE",
    country_code: "IN",
    region: "",
    city: "Kochi",
    deadline: null,
    published_at: "2026-10-01T00:00:00Z",
    closed_at: null,
    close_reason: "",
    created_at: "2026-09-30T00:00:00Z",
    organization: null,
    posted_by: { id: "u-2", display_name: "Grace Hopper", headline: "", avatar_url: null },
    skills: [],
    job: null,
    event: {
      event_status: "REGISTRATION_OPEN",
      format: "IN_PERSON",
      start_at: "2026-11-20T12:30:00Z",
      end_at: "2026-11-20T14:30:00Z",
      timezone: "Asia/Kolkata",
      venue: "Kerala Startup Mission",
      online_url: "",
      has_online_url: false,
      capacity: 40,
      confirmed_count: 0,
      registration_opens_at: null,
      attendee_visibility: "ATTENDEES",
      ...overrides,
    },
    viewer: makeViewer({ can_register: true, ...viewer }),
  };
  return detail;
}

const going = { id: "reg-1", status: "CONFIRMED" as const, waitlist_position: null };
const waiting = { id: "reg-1", status: "WAITLISTED" as const, waitlist_position: 3 };

beforeEach(() => vi.spyOn(window, "confirm").mockReturnValue(true));
afterEach(() => vi.unstubAllGlobals());

describe("registering for an event", () => {
  it("takes a place and then shows that you are going", async () => {
    let current = event();
    const api = mockApi({
      [`GET ${PAGE}`]: () => json(current),
      [`POST ${EVENTS}register/`]: () => {
        current = event({ confirmed_count: 1 }, { can_register: false, registration: going });
        return json(going, 201);
      },
    });
    renderApp("/opportunities/ev-1", makeSession());
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Registration" });
    await user.click(within(panel).getByRole("button", { name: "Register" }));

    expect(await within(panel).findByText("You are going")).toBeVisible();
    expect(api.count(`POST ${EVENTS}register/`)).toBe(1);
    expect(within(panel).getByRole("button", { name: "Cancel registration" })).toBeVisible();
    expect(within(panel).queryByRole("button", { name: "Register" })).toBeNull();
  });

  it("offers the waitlist when the event is full, and says where you are in it", async () => {
    let current = event({ capacity: 2, confirmed_count: 2 });
    mockApi({
      [`GET ${PAGE}`]: () => json(current),
      [`POST ${EVENTS}register/`]: () => {
        current = event(
          { capacity: 2, confirmed_count: 2 },
          { can_register: false, registration: waiting },
        );
        return json(waiting, 201);
      },
    });
    renderApp("/opportunities/ev-1", makeSession());
    const user = userEvent.setup();

    expect(await screen.findByText(/Every place is taken/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Join the waitlist" }));

    expect(await screen.findByText(/You are number 3 in the queue/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Leave the waitlist" })).toBeVisible();
  });

  it("cancels after confirmation, and offers to register again", async () => {
    let current = event({ confirmed_count: 1 }, { can_register: false, registration: going });
    const api = mockApi({
      [`GET ${PAGE}`]: () => json(current),
      [`POST ${EVENTS}cancel-registration/`]: () => {
        current = event({}, { registration: { ...going, status: "CANCELLED" } });
        return json({ ...going, status: "CANCELLED" });
      },
    });
    renderApp("/opportunities/ev-1", makeSession());
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Cancel registration" }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("next person waiting"));
    expect(await screen.findByText(/You cancelled your registration/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Register" })).toBeVisible();
    expect(api.count(`POST ${EVENTS}cancel-registration/`)).toBe(1);
  });

  it("does not cancel when the confirmation is declined", async () => {
    vi.mocked(window.confirm).mockReturnValue(false);
    const api = mockApi({
      [`GET ${PAGE}`]: () => json(event({}, { can_register: false, registration: going })),
    });
    renderApp("/opportunities/ev-1", makeSession());

    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Cancel registration" }));

    expect(api.count(`POST ${EVENTS}cancel-registration/`)).toBe(0);
  });

  it("explains when registration closed while the page was open", async () => {
    mockApi({
      [`GET ${PAGE}`]: () => json(event()),
      [`POST ${EVENTS}register/`]: () =>
        apiError(409, "registration_closed", "Registration for this event is not open."),
    });
    renderApp("/opportunities/ev-1", makeSession());

    await userEvent.setup().click(await screen.findByRole("button", { name: "Register" }));

    expect(await screen.findByText("Registration for this event has just closed.")).toBeVisible();
  });

  it("asks a visitor to sign in and an unverified user to confirm their email", async () => {
    mockApi({ [`GET ${PAGE}`]: () => json(event({}, { can_register: false })) });
    renderApp("/opportunities/ev-1");
    expect(await screen.findByRole("link", { name: "Sign in to register" })).toHaveAttribute(
      "href",
      "/login?next=%2Fopportunities%2Fev-1",
    );

    cleanup();
    vi.unstubAllGlobals();
    mockApi({ [`GET ${PAGE}`]: () => json(event()) });
    renderApp("/opportunities/ev-1", makeSession(makeMe({ email_verified: false })));
    expect(await screen.findByText(/Confirm your email address before registering/)).toBeVisible();
  });

  it("says when registration is closed or not open yet, and nothing once it is over", async () => {
    mockApi({
      [`GET ${PAGE}`]: () =>
        json(event({ event_status: "REGISTRATION_CLOSED" }, { can_register: false })),
    });
    renderApp("/opportunities/ev-1", makeSession());
    expect(await screen.findByText("Registration for this event is closed.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Register" })).toBeNull();
  });

  it("lists who is going when the organizers allow it, and stays quiet when they do not", async () => {
    const ada = { id: "u-7", display_name: "Ada Lovelace", headline: "", avatar_url: null };
    mockApi({
      [`GET ${PAGE}`]: () => json(event({ confirmed_count: 3 })),
      [`GET ${EVENTS}attendees/`]: () => json([ada]),
    });
    renderApp("/opportunities/ev-1");

    const people = await screen.findByRole("list", { name: "People going" });
    expect(within(people).getByRole("link", { name: "Ada Lovelace" })).toHaveAttribute(
      "href",
      "/users/u-7",
    );
    // Two more are going whom this viewer is not shown.
    expect(screen.getByText("and 2 more.")).toBeVisible();

    cleanup();
    vi.unstubAllGlobals();
    const denied = mockApi({
      [`GET ${PAGE}`]: () => json(event({ confirmed_count: 3 })),
      [`GET ${EVENTS}attendees/`]: () => apiError(403, "permission_denied", "No."),
    });
    renderApp("/opportunities/ev-1");
    expect(await screen.findByRole("region", { name: "Registration" })).toBeVisible();
    await waitFor(() => expect(denied.count(`GET ${EVENTS}attendees/`)).toBe(1));
    expect(screen.queryByText("Who is going")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("the check-in code", () => {
  const mine = (overrides: Record<string, unknown> = {}) => ({
    ...going,
    checkin_code: "signed-code-for-ada",
    checked_in_at: null,
    ...overrides,
  });
  const routes = (registration: unknown) => ({
    [`GET ${PAGE}`]: () =>
      json(event({ confirmed_count: 1 }, { can_register: false, registration: going })),
    [`GET ${EVENTS}my-registration/`]: () => json(registration),
  });

  it("is shown as a QR code only when asked for", async () => {
    mockApi(routes(mine()));
    renderApp("/opportunities/ev-1", makeSession());
    const user = userEvent.setup();

    const show = await screen.findByRole("button", { name: "Show check-in code" });
    expect(screen.queryByRole("img", { name: "Your check-in code" })).toBeNull();
    await user.click(show);

    const code = screen.getByRole("img", { name: "Your check-in code" });
    // Drawn here from the text the server gave: dark modules on white.
    expect(code.querySelector("path")?.getAttribute("d")).toMatch(/^M\d+ \d+h1v1h-1z/);
    expect(code.querySelector("rect")).toHaveAttribute("fill", "#ffffff");
    // The code itself is not written out where it could be copied or read aloud.
    expect(document.body).not.toHaveTextContent("signed-code-for-ada");

    await user.click(screen.getByRole("button", { name: "Hide check-in code" }));
    expect(screen.queryByRole("img", { name: "Your check-in code" })).toBeNull();
  });

  it("gives way to the fact of being checked in", async () => {
    mockApi(routes(mine({ checkin_code: null, checked_in_at: "2026-11-20T12:10:00Z" })));
    renderApp("/opportunities/ev-1", makeSession());

    expect(await screen.findByText("Checked in")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Show check-in code" })).toBeNull();
  });

  it("is not offered to someone on the waitlist", async () => {
    const api = mockApi({
      [`GET ${PAGE}`]: () => json(event({}, { can_register: false, registration: waiting })),
    });
    renderApp("/opportunities/ev-1", makeSession());

    expect(await screen.findByText(/You are number 3 in the queue/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Show check-in code" })).toBeNull();
    expect(api.count(`GET ${EVENTS}my-registration/`)).toBe(0);
  });
});

describe("running registrations", () => {
  const registration = (id: string, name: string, status: Registration["status"]) => ({
    id,
    status,
    person: { id: `u-${id}`, display_name: name, headline: "", avatar_url: null },
    waitlisted_at: status === "WAITLISTED" ? "2026-10-10T09:00:00Z" : null,
    created_at: "2026-10-10T09:00:00Z",
  });
  const summary: RegistrationSummary = {
    counts: { CONFIRMED: 1, WAITLISTED: 1, CANCELLED: 0 },
    capacity: 1,
    checked_in: 0,
    checkin_open: false,
  };
  const managed = (overrides: Partial<EventDetail> = {}) =>
    event(overrides, { can_manage: true, can_register: false, editable_fields: ["description"] });
  const routes = (overrides: Partial<EventDetail> = {}) => ({
    [`GET ${PAGE}`]: () => json(managed(overrides)),
    [`GET ${PAGE}communities/`]: () => json([]),
    [`GET ${PAGE}communities/options/`]: () => json([]),
    [`GET ${EVENTS}registrations/summary/`]: () => json(summary),
    [`GET ${EVENTS}registrations/`]: () =>
      page([
        registration("r1", "Ada Lovelace", "CONFIRMED"),
        registration("r2", "Bob Kahn", "WAITLISTED"),
      ]),
  });

  it("shows the organizers who is coming and who is waiting", async () => {
    const api = mockApi(routes());
    renderApp("/opportunities/ev-1", makeSession());
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Registrations" });
    const rows = await within(panel).findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Ada Lovelace");
    expect(rows[0]).toHaveTextContent("Going");
    expect(rows[1]).toHaveTextContent("On the waitlist");
    expect(panel).toHaveTextContent("1 going of 1 places, 1 on the waitlist.");

    await user.selectOptions(within(panel).getByLabelText("Show"), "WAITLISTED");
    await waitFor(() =>
      expect(api.last(`GET ${EVENTS}registrations/`)?.url.searchParams.get("status")).toBe(
        "WAITLISTED",
      ),
    );
  });

  it("removes someone after confirmation", async () => {
    const api = mockApi({
      ...routes(),
      [`POST ${EVENTS}registrations/r1/remove/`]: () =>
        json(registration("r1", "Ada Lovelace", "CANCELLED")),
    });
    renderApp("/opportunities/ev-1", makeSession());

    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Remove Ada Lovelace" }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("Remove Ada Lovelace?"));
    await waitFor(() => expect(api.count(`POST ${EVENTS}registrations/r1/remove/`)).toBe(1));
  });

  it("closes registration by hand, and offers to open it when it is closed", async () => {
    const api = mockApi({
      ...routes(),
      [`POST ${EVENTS}close-registration/`]: () => new Response(null, { status: 204 }),
    });
    renderApp("/opportunities/ev-1", makeSession());

    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Close registration" }));
    await waitFor(() => expect(api.count(`POST ${EVENTS}close-registration/`)).toBe(1));

    cleanup();
    vi.unstubAllGlobals();
    mockApi(routes({ event_status: "REGISTRATION_CLOSED" }));
    renderApp("/opportunities/ev-1", makeSession());
    expect(await screen.findByRole("button", { name: "Open registration" })).toBeVisible();
  });
});

describe("my events", () => {
  const mine: MyEvent[] = [
    {
      id: "reg-1",
      status: "WAITLISTED",
      created_at: "2026-10-10T09:00:00Z",
      event: {
        id: "ev-1",
        title: "Kochi Python Meetup",
        status: "PUBLISHED",
        event_status: "REGISTRATION_OPEN",
        format: "IN_PERSON",
        start_at: "2026-11-20T12:30:00Z",
        end_at: "2026-11-20T14:30:00Z",
        timezone: "Asia/Kolkata",
        venue: "Kerala Startup Mission",
        city: "Kochi",
        organization: { id: "org-1", name: "Example Labs" },
      },
    },
  ];

  it("lists the events with when, where and how I stand, reached from the menu", async () => {
    mockApi({ "GET /api/v1/users/me/event-registrations/": () => json(mine) });
    renderApp("/my/events", makeSession());

    expect(await screen.findByRole("heading", { name: "My events" })).toBeVisible();
    const list = screen.getByRole("region", { name: "Your events" });
    const row = within(list).getByRole("listitem");
    expect(within(row).getByRole("link", { name: "Kochi Python Meetup" })).toHaveAttribute(
      "href",
      "/opportunities/ev-1",
    );
    expect(row).toHaveTextContent(/6:00\sPM – 8:00\sPM/);
    expect(row).toHaveTextContent("Example Labs · In person · Kerala Startup Mission, Kochi");
    expect(row).toHaveTextContent("On the waitlist");
    expect(screen.getByRole("link", { name: "My events" })).toHaveAttribute("href", "/my/events");
  });

  it("has an empty state and requires signing in", async () => {
    mockApi({ "GET /api/v1/users/me/event-registrations/": () => json([]) });
    renderApp("/my/events", makeSession());
    expect(await screen.findByRole("link", { name: "Find an event" })).toHaveAttribute(
      "href",
      "/opportunities?type=EVENT",
    );

    cleanup();
    vi.unstubAllGlobals();
    mockApi({});
    const router = renderApp("/my/events");
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
  });
});
