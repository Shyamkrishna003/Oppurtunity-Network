import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Connection, ConnectionState } from "../features/connections/types";
import type { PublicProfile } from "../features/profile/types";
import { makeSession } from "../test/fixtures";
import { apiError, json, mockApi, noContent } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const LIST = "GET /api/v1/connections/";
const SUMMARY = "GET /api/v1/connections/summary/";
const ASK = "POST /api/v1/connections/";
const PROFILE = "GET /api/v1/users/u-2/";
const page = <T,>(results: T[]) => json({ results, next: null, previous: null });

function connection(id: string, state: ConnectionState, name = "Grace Hopper"): Connection {
  return {
    id,
    state,
    user: { id: "u-2", display_name: name, headline: "Compiler engineer", avatar_url: null },
    created_at: "2026-10-10T09:30:00Z",
  };
}

function profile(overrides: Partial<PublicProfile> = {}): PublicProfile {
  return {
    id: "u-2",
    is_self: false,
    connection: null,
    display_name: "Grace Hopper",
    headline: "",
    bio: "",
    avatar_url: null,
    country_code: "",
    region: "",
    city: "",
    work_mode_preference: "",
    experience_level: "",
    skills: { has: [], interested: [] },
    email: null,
    experiences: [],
    educations: [],
    ...overrides,
  };
}

/** A list endpoint that answers by the `state` asked for, and remembers what was asked. */
function lists(byState: Partial<Record<ConnectionState, Connection[]>>) {
  return ({ url }: { url: URL }) =>
    page(byState[url.searchParams.get("state") as ConnectionState] ?? []);
}

afterEach(() => vi.unstubAllGlobals());

describe("connections page", () => {
  it("lists the viewer's connections, with the number of requests waiting", async () => {
    mockApi({
      [LIST]: lists({ CONNECTED: [connection("c-1", "CONNECTED")] }),
      [SUMMARY]: () => json({ incoming: 2 }),
    });
    renderApp("/connections", makeSession());

    const list = await screen.findByRole("region", { name: "Your connections" });
    expect(await within(list).findByRole("link", { name: "Grace Hopper" })).toHaveAttribute(
      "href",
      "/users/u-2",
    );
    expect(within(list).getByText(/Compiler engineer/)).toBeVisible();
    expect(within(list).getByRole("link", { name: "Connections" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await within(list).findByRole("link", { name: "Requests (2)" })).toHaveAttribute(
      "href",
      "/connections?show=requests",
    );
    expect(within(list).getByRole("button", { name: "Remove Grace Hopper" })).toBeVisible();
  });

  it("explains an empty list and offers to retry a failed one", async () => {
    let fail = true;
    mockApi({
      [LIST]: () => (fail ? apiError(403, "forbidden", "Something broke.") : page([])),
      [SUMMARY]: () => json({ incoming: 0 }),
    });
    renderApp("/connections", makeSession());

    expect(await screen.findByRole("alert")).toHaveTextContent("Something broke.");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText(/You have no connections yet/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Requests" })).toBeVisible();
  });

  it("accepts a request, which then leaves the list of requests", async () => {
    let waiting = [connection("c-1", "INCOMING")];
    const api = mockApi({
      [LIST]: ({ url }) => page(url.searchParams.get("state") === "INCOMING" ? waiting : []),
      [SUMMARY]: () => json({ incoming: waiting.length }),
      "POST /api/v1/connections/c-1/accept/": () => {
        waiting = [];
        return json(connection("c-1", "CONNECTED"));
      },
    });
    renderApp("/connections?show=requests", makeSession());

    await userEvent.click(await screen.findByRole("button", { name: "Accept Grace Hopper" }));

    expect(await screen.findByText("Nobody is waiting for your answer.")).toBeVisible();
    expect(api.count("POST /api/v1/connections/c-1/accept/")).toBe(1);
    expect(screen.getByRole("link", { name: "Requests" })).toBeVisible();
  });

  it("declines a request without asking for confirmation", async () => {
    let waiting = [connection("c-1", "INCOMING")];
    const api = mockApi({
      [LIST]: lists({ INCOMING: waiting }),
      [SUMMARY]: () => json({ incoming: waiting.length }),
      "POST /api/v1/connections/c-1/decline/": () => {
        waiting = [];
        return noContent();
      },
    });
    renderApp("/connections?show=requests", makeSession());

    await userEvent.click(await screen.findByRole("button", { name: "Decline Grace Hopper" }));

    await waitFor(() => expect(api.count("POST /api/v1/connections/c-1/decline/")).toBe(1));
  });

  it("takes back a request the viewer sent", async () => {
    const api = mockApi({
      [LIST]: lists({ OUTGOING: [connection("c-1", "OUTGOING")] }),
      [SUMMARY]: () => json({ incoming: 0 }),
      "DELETE /api/v1/connections/c-1/": () => noContent(),
    });
    renderApp("/connections?show=sent", makeSession());

    expect(await screen.findByRole("link", { name: "Sent" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Cancel request to Grace Hopper" }),
    );

    await waitFor(() => expect(api.count("DELETE /api/v1/connections/c-1/")).toBe(1));
  });

  it("only removes a connection once the viewer confirms", async () => {
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    const api = mockApi({
      [LIST]: lists({ CONNECTED: [connection("c-1", "CONNECTED")] }),
      [SUMMARY]: () => json({ incoming: 0 }),
      "DELETE /api/v1/connections/c-1/": () => noContent(),
    });
    renderApp("/connections", makeSession());
    const remove = await screen.findByRole("button", { name: "Remove Grace Hopper" });

    await userEvent.click(remove);
    expect(confirm).toHaveBeenCalledWith("Remove Grace Hopper from your connections?");
    expect(api.count("DELETE /api/v1/connections/c-1/")).toBe(0);

    confirm.mockReturnValue(true);
    await userEvent.click(remove);
    await waitFor(() => expect(api.count("DELETE /api/v1/connections/c-1/")).toBe(1));
  });

  it("sends a signed-out visitor to sign in", async () => {
    mockApi({});
    const router = renderApp("/connections");

    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
  });
});

describe("connecting from a profile", () => {
  it("asks to connect, then offers to take the request back", async () => {
    let current: PublicProfile["connection"] = null;
    const api = mockApi({
      [PROFILE]: () => json(profile({ connection: current })),
      [ASK]: () => {
        current = { id: "c-1", state: "OUTGOING" };
        return json(connection("c-1", "OUTGOING"), 201);
      },
    });
    renderApp("/users/u-2", makeSession());

    await userEvent.click(await screen.findByRole("button", { name: "Connect with Grace Hopper" }));

    expect(
      await screen.findByRole("button", { name: "Cancel request to Grace Hopper" }),
    ).toBeVisible();
    expect(api.last(ASK)?.body).toEqual({ user_id: "u-2" });
  });

  it("offers to answer a request the profile's owner made", async () => {
    mockApi({
      [PROFILE]: () => json(profile({ connection: { id: "c-1", state: "INCOMING" } })),
    });
    renderApp("/users/u-2", makeSession());

    expect(await screen.findByRole("button", { name: "Accept Grace Hopper" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Decline Grace Hopper" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /Connect with/ })).not.toBeInTheDocument();
  });

  it("says why asking was refused and shows how things stand now", async () => {
    let current: PublicProfile["connection"] = null;
    mockApi({
      [PROFILE]: () => json(profile({ connection: current })),
      [ASK]: () => {
        current = { id: "c-1", state: "INCOMING" };
        return apiError(
          409,
          "request_waiting",
          "This person has already asked to connect with you. Answer their request.",
        );
      },
    });
    renderApp("/users/u-2", makeSession());

    await userEvent.click(await screen.findByRole("button", { name: "Connect with Grace Hopper" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already asked to connect/);
    expect(await screen.findByRole("button", { name: "Accept Grace Hopper" })).toBeVisible();
  });

  it("shows no connection controls on the viewer's own profile", async () => {
    mockApi({ [PROFILE]: () => json(profile({ is_self: true })) });
    renderApp("/users/u-2", makeSession());

    expect(await screen.findByRole("link", { name: "Edit profile" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /Connect/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Block" })).not.toBeInTheDocument();
  });
});
