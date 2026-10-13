import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Conversation, Message } from "../features/messaging/api";
import { makeMe, makeSession } from "../test/fixtures";
import { apiError, json, mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const INBOX = "GET /api/v1/conversations/";
const UNREAD = "GET /api/v1/conversations/unread-count/";
const ONE = "/api/v1/conversations/c-1/";
const page = <T,>(results: T[], next: string | null = null) =>
  json({ results, next, previous: null });

const ME = makeMe();
const grace = { id: "u-2", display_name: "Grace Hopper", headline: "", avatar_url: null };

function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: "c-1",
    other: grace,
    last_message_at: "2026-10-10T09:30:00Z",
    last_message_preview: "See you at the meetup",
    unread_count: 0,
    other_read_at: null,
    created_at: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

let serial = 0;
function message(body: string, mine: boolean, overrides: Partial<Message> = {}): Message {
  serial += 1;
  return {
    id: `m-${String(serial)}`,
    conversation_id: "c-1",
    sender_id: mine ? ME.id : grace.id,
    body,
    client_id: `client-${String(serial)}`,
    created_at: `2026-10-10T09:${String(10 + serial)}:00Z`,
    ...overrides,
  };
}

/** A thread as the API gives it: newest first. */
const thread = (...oldestFirst: Message[]) => page([...oldestFirst].reverse());

afterEach(() => vi.unstubAllGlobals());

describe("inbox", () => {
  it("lists conversations with who, the latest message and what is unread", async () => {
    mockApi({
      [UNREAD]: () => json({ count: 1 }),
      [INBOX]: () =>
        page([
          conversation({ unread_count: 2 }),
          conversation({
            id: "c-2",
            other: { ...grace, id: "u-3", display_name: "Linus T" },
            last_message_preview: "",
          }),
        ]),
    });
    renderApp("/messages", makeSession());

    const list = await screen.findByRole("region", { name: "Your conversations" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByRole("link")).toHaveAttribute("href", "/messages/c-1");
    expect(rows[0]).toHaveTextContent("Grace Hopper");
    expect(rows[0]).toHaveTextContent("See you at the meetup");
    expect(rows[0]).toHaveTextContent("2 unread");
    expect(rows[1]).toHaveTextContent("No messages yet.");
    expect(rows[1]).not.toHaveTextContent("unread");
    // The navigation shows how many conversations are waiting.
    expect(await screen.findByRole("link", { name: "Messages 1 unread" })).toHaveAttribute(
      "href",
      "/messages",
    );
  });

  it("has an empty state that points to connections, and requires signing in", async () => {
    mockApi({ [INBOX]: () => page([]) });
    renderApp("/messages", makeSession());
    expect(await screen.findByRole("link", { name: "Your connections" })).toHaveAttribute(
      "href",
      "/connections",
    );
    expect(screen.getByRole("link", { name: "Messages" })).toBeVisible(); // no badge at zero
  });

  it("sends visitors to sign in", async () => {
    mockApi({});
    const router = renderApp("/messages");
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
  });
});

describe("a conversation", () => {
  const routes = (messages: Response, detail = conversation()) => ({
    [`GET ${ONE}`]: () => json(detail),
    [`GET ${ONE}messages/`]: () => messages.clone(),
  });

  it("shows the thread oldest first, with whose message each is", async () => {
    mockApi(routes(thread(message("Hi Ada", false), message("Hi Grace!", true))));
    renderApp("/messages/c-1", makeSession());

    const region = await screen.findByRole("region", {
      name: "Conversation with Grace Hopper",
    });
    const bubbles = within(region)
      .getAllByRole("listitem")
      .filter((item) => item.classList.contains("message"));
    expect(bubbles.map((bubble) => bubble.querySelector(".message-body")?.textContent)).toEqual([
      "Hi Ada",
      "Hi Grace!",
    ]);
    expect(bubbles[0]).not.toHaveClass("message-mine");
    expect(bubbles[1]).toHaveClass("message-mine");
    // One day, named once.
    expect(within(region).getAllByText(/Oct 10, 2026/)).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Grace Hopper" })).toHaveAttribute(
      "href",
      "/users/u-2",
    );
  });

  it("sends on Enter, shows the message at once and keeps it when the server answers", async () => {
    let resolve: (response: Response) => void = () => undefined;
    const api = mockApi({
      ...routes(thread(message("Hi Ada", false))),
      [`POST ${ONE}messages/`]: () => new Promise<Response>((done) => (resolve = done)),
    });
    renderApp("/messages/c-1", makeSession());
    const user = userEvent.setup();

    const box = await screen.findByLabelText("Message");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await user.type(box, "  On my way{Shift>}{Enter}{/Shift}second line  {Enter}");

    // There before the server has said anything, and the box is ready for the next one.
    expect(await screen.findByText(/On my way\s+second line/)).toBeVisible();
    expect(screen.getByText(/Sending…/)).toBeVisible();
    expect(box).toHaveValue("");
    const sent = api.last(`POST ${ONE}messages/`)?.body as { body: string; client_id: string };
    expect(sent.body).toBe("On my way\nsecond line");
    expect(sent.client_id).toMatch(/^[0-9a-f-]{36}$/);

    resolve(json(message("On my way\nsecond line", true, { client_id: sent.client_id }), 201));
    await waitFor(() => expect(screen.queryByText(/Sending…/)).toBeNull());
    expect(screen.getAllByText(/On my way\s+second line/)).toHaveLength(1);
  });

  it("marks a message that failed and retries it with the same client ID", async () => {
    let fail = true;
    const api = mockApi({
      ...routes(thread()),
      [`POST ${ONE}messages/`]: ({ body }) =>
        fail
          ? apiError(503, "unavailable", "Try later.")
          : json(
              message("Hello", true, { client_id: (body as { client_id: string }).client_id }),
              201,
            ),
    });
    renderApp("/messages/c-1", makeSession());
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Message"), "Hello{Enter}");
    const retry = await screen.findByRole("button", { name: "Try again" });
    expect(screen.getByText("Hello")).toBeVisible(); // not lost
    const first = (api.last(`POST ${ONE}messages/`)?.body as { client_id: string }).client_id;

    fail = false;
    await user.click(retry);

    await waitFor(() => expect(screen.queryByRole("button", { name: "Try again" })).toBeNull());
    expect(api.count(`POST ${ONE}messages/`)).toBe(2);
    // The same ID, so if the first attempt did arrive after all, nothing is sent twice.
    expect((api.last(`POST ${ONE}messages/`)?.body as { client_id: string }).client_id).toBe(first);
    expect(screen.getAllByText("Hello")).toHaveLength(1);
  });

  it("says why when the server refuses a message", async () => {
    mockApi({
      ...routes(thread()),
      [`POST ${ONE}messages/`]: () =>
        apiError(422, "recipient_unavailable", "This person can no longer receive messages."),
    });
    renderApp("/messages/c-1", makeSession());

    await userEvent.setup().type(await screen.findByLabelText("Message"), "Hello{Enter}");

    expect(await screen.findByText("This person can no longer receive messages.")).toBeVisible();
  });

  it("tells the server how far has been read when there is something unread", async () => {
    const incoming = message("Are you coming?", false);
    const api = mockApi({
      ...routes(thread(message("Hi", true), incoming), conversation({ unread_count: 1 })),
      [`POST ${ONE}read/`]: () => new Response(null, { status: 204 }),
    });
    renderApp("/messages/c-1", makeSession());

    await waitFor(() =>
      expect(api.last(`POST ${ONE}read/`)?.body).toEqual({ up_to_message_id: incoming.id }),
    );
  });

  it("does not report reading when nothing is unread", async () => {
    const api = mockApi(routes(thread(message("Hi Ada", false))));
    renderApp("/messages/c-1", makeSession());

    await screen.findByText("Hi Ada");
    expect(api.count(`POST ${ONE}read/`)).toBe(0);
  });

  it("shows Seen under the last of my messages the other person has read", async () => {
    const read = message("First", true);
    const unread = message("Second", true);
    mockApi(routes(thread(read, unread), conversation({ other_read_at: read.created_at })));
    renderApp("/messages/c-1", makeSession());

    const first = (await screen.findByText("First")).closest("li")!;
    expect(first).toHaveTextContent("Seen");
    expect(screen.getByText("Second").closest("li")).not.toHaveTextContent("Seen");
    expect(screen.getAllByText(/Seen/)).toHaveLength(1);
  });

  it("loads earlier messages on request", async () => {
    const older = message("Much earlier", false, { created_at: "2026-10-01T08:00:00Z" });
    const api = mockApi({
      [`GET ${ONE}`]: () => json(conversation()),
      [`GET ${ONE}messages/`]: ({ url }) =>
        url.searchParams.get("cursor")
          ? page([older])
          : page(
              [message("Latest", false)],
              "http://localhost/api/v1/conversations/c-1/messages/?cursor=abc",
            ),
    });
    renderApp("/messages/c-1", makeSession());
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Show earlier messages" }));

    expect(await screen.findByText("Much earlier")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Show earlier messages" })).toBeNull();
    expect(api.count(`GET ${ONE}messages/`)).toBe(2);
  });

  it("explains a conversation that is gone", async () => {
    mockApi({
      [`GET ${ONE}`]: () => apiError(404, "not_found", "Not found."),
      [`GET ${ONE}messages/`]: () => apiError(404, "not_found", "Not found."),
    });
    renderApp("/messages/c-1", makeSession());

    expect(await screen.findByRole("heading", { name: "Conversation not found" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Back to messages" })).toHaveAttribute(
      "href",
      "/messages",
    );
  });
});
