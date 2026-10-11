import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AppNotification, NotificationPreference } from "../features/notifications/types";
import { FakeSocket } from "../test/fakeSocket";
import { makeMe, makeSession } from "../test/fixtures";
import { json, mockApi, noContent } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const LIST = "GET /api/v1/notifications/";
const COUNT = "GET /api/v1/notifications/unread-count/";
const PREFERENCES = "/api/v1/users/me/notification-preferences/";
const page = <T,>(results: T[]) => json({ results, next: null, previous: null });

function notification(id: string, overrides: Partial<AppNotification> = {}): AppNotification {
  return {
    id,
    type: "SHARE_APPROVED",
    title: "Kochi Developers approved “Backend Engineer”",
    body: "It is now shown to the community's members.",
    url: "/opportunities/opp-1",
    actor: { id: "u-2", display_name: "Grace Hopper", headline: "", avatar_url: null },
    is_read: false,
    created_at: "2026-10-10T09:30:00Z",
    ...overrides,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("unread badge", () => {
  it("shows the number of unread notifications to a signed-in user", async () => {
    mockApi({
      [COUNT]: () => json({ count: 3 }),
      "GET /readyz": () => json({ status: "ok", checks: {} }),
    });
    renderApp("/", makeSession());

    const bell = await screen.findByRole("link", { name: "Notifications 3 unread" });
    expect(bell).toHaveAttribute("href", "/notifications");
  });

  it("shows no number when there is nothing unread, and caps a large one", async () => {
    let count = 0;
    mockApi({
      [COUNT]: () => json({ count }),
      "GET /readyz": () => json({ status: "ok", checks: {} }),
    });
    renderApp("/", makeSession());
    expect(await screen.findByRole("link", { name: "Notifications" })).toBeVisible();

    vi.unstubAllGlobals();
    count = 250;
    mockApi({
      [COUNT]: () => json({ count }),
      "GET /readyz": () => json({ status: "ok", checks: {} }),
    });
    renderApp("/", makeSession());
    expect(await screen.findByRole("link", { name: "Notifications 99+ unread" })).toBeVisible();
  });

  it("is not shown to visitors, and nothing is requested for them", async () => {
    const api = mockApi({ "GET /readyz": () => json({ status: "ok", checks: {} }) });
    renderApp("/");

    expect(await screen.findByRole("link", { name: "Sign in" })).toBeVisible();
    expect(screen.queryByRole("link", { name: /Notifications/ })).toBeNull();
    expect(api.count(COUNT)).toBe(0);
  });
});

describe("notifications page", () => {
  it("lists notifications, marking unread ones, and opens one as read", async () => {
    const api = mockApi({
      [COUNT]: () => json({ count: 1 }),
      [LIST]: () =>
        page([
          notification("n-1"),
          notification("n-2", {
            title: "“Backend Engineer” has expired",
            actor: null,
            is_read: true,
          }),
        ]),
      "POST /api/v1/notifications/n-1/read/": noContent,
      "GET /api/v1/opportunities/opp-1/": () => json({}, 404),
    });
    const router = renderApp("/notifications", makeSession());
    const user = userEvent.setup();

    const list = await screen.findByRole("region", { name: "Your notifications" });
    const rows = await within(list).findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("New");
    expect(rows[0]).toHaveTextContent("It is now shown to the community's members.");
    expect(rows[1]).not.toHaveTextContent("New");
    expect(within(rows[1]!).queryByRole("button")).toBeNull();

    await user.click(within(rows[0]!).getByRole("link"));

    await waitFor(() => expect(router.state.location.pathname).toBe("/opportunities/opp-1"));
    expect(api.count("POST /api/v1/notifications/n-1/read/")).toBe(1);
  });

  it("marks one as read without leaving, and all at once", async () => {
    const api = mockApi({
      [COUNT]: () => json({ count: 2 }),
      [LIST]: () => page([notification("n-1"), notification("n-2")]),
      "POST /api/v1/notifications/n-2/read/": noContent,
      "POST /api/v1/notifications/read-all/": noContent,
    });
    const router = renderApp("/notifications", makeSession());
    const user = userEvent.setup();

    const buttons = await screen.findAllByRole("button", { name: /^Mark as read/ });
    await user.click(buttons[1]!);
    await waitFor(() => expect(api.count("POST /api/v1/notifications/n-2/read/")).toBe(1));
    expect(router.state.location.pathname).toBe("/notifications");

    await user.click(screen.getByRole("button", { name: "Mark all as read" }));
    await waitFor(() => expect(api.count("POST /api/v1/notifications/read-all/")).toBe(1));
  });

  it("filters to unread through the address", async () => {
    const api = mockApi({
      [COUNT]: () => json({ count: 0 }),
      [LIST]: ({ url }) =>
        page(
          url.searchParams.get("unread") === "true" ? [] : [notification("n-1", { is_read: true })],
        ),
    });
    const router = renderApp("/notifications", makeSession());
    const user = userEvent.setup();

    await screen.findByText(/approved “Backend Engineer”/);
    expect(screen.queryByRole("button", { name: "Mark all as read" })).toBeNull();
    await user.click(screen.getByLabelText("Unread only"));

    expect(await screen.findByText("You have read everything.")).toBeVisible();
    expect(router.state.location.search).toBe("?unread=true");
    expect(api.last(LIST)?.url.searchParams.get("unread")).toBe("true");
  });

  it("has an empty state and requires signing in", async () => {
    mockApi({ [COUNT]: () => json({ count: 0 }), [LIST]: () => page([]) });
    renderApp("/notifications", makeSession());
    expect(await screen.findByText(/Nothing yet/)).toBeVisible();
  });

  it("sends visitors to sign in", async () => {
    mockApi({});
    const router = renderApp("/notifications");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(router.state.location.search).toBe("?next=%2Fnotifications");
  });
});

describe("live updates", () => {
  const TICKET = "POST /api/v1/auth/ws-ticket/";
  const ticket = () => json({ ticket: "ticket-1", expires_in: 30 });

  async function connected() {
    await waitFor(() => expect(FakeSocket.opened).toHaveLength(1));
    act(() => FakeSocket.latest.hello());
    return FakeSocket.latest;
  }

  it("shows a notification the moment it is created, without reloading", async () => {
    let existing = [notification("n-1", { is_read: true })];
    mockApi({
      [TICKET]: ticket,
      [COUNT]: () => json({ count: existing.filter((n) => !n.is_read).length }),
      [LIST]: () => page(existing),
    });
    FakeSocket.install();
    renderApp("/notifications", makeSession());
    const socket = await connected();
    const list = await screen.findByRole("region", { name: "Your notifications" });
    expect(await within(list).findAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Notifications" })).toBeVisible();

    const created = notification("n-2", { title: "Grace Hopper approved your request to join" });
    existing = [created, ...existing];
    act(() => socket.event("notification.created", { ...created }));

    expect(
      await within(list).findByRole("link", { name: /approved your request to join/ }),
    ).toBeVisible();
    expect(await screen.findByRole("link", { name: "Notifications 1 unread" })).toBeVisible();
  });

  it("clears the badge when the notifications are read in another tab", async () => {
    let count = 2;
    mockApi({
      [TICKET]: ticket,
      [COUNT]: () => json({ count }),
      "GET /readyz": () => json({ status: "ok", checks: {} }),
    });
    FakeSocket.install();
    renderApp("/", makeSession());
    const socket = await connected();
    expect(await screen.findByRole("link", { name: "Notifications 2 unread" })).toBeVisible();

    count = 0;
    act(() => socket.event("notification.read", { all: true }));

    expect(await screen.findByRole("link", { name: "Notifications" })).toBeVisible();
  });

  it("catches up on what it missed after the connection drops and comes back", async () => {
    let count = 0;
    const api = mockApi({
      [TICKET]: ticket,
      [COUNT]: () => json({ count }),
      "GET /readyz": () => json({ status: "ok", checks: {} }),
    });
    FakeSocket.install();
    renderApp("/", makeSession());
    const first = await connected();
    expect(await screen.findByRole("link", { name: "Notifications" })).toBeVisible();

    // Something happens while there is no connection, so nothing is pushed for it.
    count = 4;
    act(() => first.serverCloses(4401));
    await waitFor(() => expect(FakeSocket.opened).toHaveLength(2));
    act(() => FakeSocket.latest.hello());

    expect(await screen.findByRole("link", { name: "Notifications 4 unread" })).toBeVisible();
    expect(api.count(TICKET)).toBe(2);
  });

  it("is closed on signing out, and never opened for a visitor", async () => {
    const api = mockApi({
      [TICKET]: ticket,
      [COUNT]: () => json({ count: 0 }),
      "POST /api/v1/auth/logout/": noContent,
      "GET /readyz": () => json({ status: "ok", checks: {} }),
    });
    FakeSocket.install();
    renderApp("/", makeSession());
    const socket = await connected();

    await userEvent.setup().click(await screen.findByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("link", { name: "Sign in" })).toBeVisible();
    expect(socket.closedByClient).toBe(1000);
    expect(FakeSocket.opened).toHaveLength(1);
    expect(api.count(TICKET)).toBe(1);
  });
});

describe("notification settings", () => {
  const preferences: NotificationPreference[] = [
    {
      category: "REVIEW",
      title: "Things waiting for my review",
      description: "Requests to join and opportunities waiting for your decision.",
      in_app: true,
      email: false,
    },
    {
      category: "POSTINGS",
      title: "My opportunities",
      description: "What communities decide about your opportunities.",
      in_app: true,
      email: true,
    },
  ];

  it("shows each category with its current choice and saves a change on its own", async () => {
    const api = mockApi({
      [COUNT]: () => json({ count: 0 }),
      [`GET ${PREFERENCES}`]: () => json({ preferences }),
      [`PUT ${PREFERENCES}`]: ({ body }) => {
        const sent = (body as { preferences: NotificationPreference[] }).preferences[0]!;
        return json({
          preferences: preferences.map((p) =>
            p.category === sent.category ? { ...p, ...sent } : p,
          ),
        });
      },
    });
    renderApp("/settings/notifications", makeSession());
    const user = userEvent.setup();

    const reviewEmail = await screen.findByLabelText("Things waiting for my review: by email");
    expect(reviewEmail).not.toBeChecked();
    expect(screen.getByLabelText("My opportunities: by email")).toBeChecked();
    expect(screen.getByText(/Emails go to ada@example.com/)).toBeVisible();

    await user.click(reviewEmail);

    await waitFor(() =>
      expect(api.last(`PUT ${PREFERENCES}`)?.body).toEqual({
        // Only the category that changed, with both of its switches.
        preferences: [{ category: "REVIEW", in_app: true, email: true }],
      }),
    );
    expect(await screen.findByText("Saved.")).toBeVisible();
    expect(screen.getByLabelText("Things waiting for my review: by email")).toBeChecked();
  });

  it("says that emails wait for the address to be confirmed", async () => {
    mockApi({
      [COUNT]: () => json({ count: 0 }),
      [`GET ${PREFERENCES}`]: () => json({ preferences }),
    });
    renderApp("/settings/notifications", makeSession(makeMe({ email_verified: false })));

    expect(await screen.findByText(/once you have confirmed it/)).toBeVisible();
  });
});
