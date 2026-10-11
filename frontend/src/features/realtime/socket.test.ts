import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FakeSocket } from "../../test/fakeSocket";
import { apiError, json, mockApi } from "../../test/mockApi";
import type { StreamStatus } from "./realtimeSlice";
import { StreamConnection, type StreamEvent } from "./socket";

const TICKET = "POST /api/v1/auth/ws-ticket/";

function setup(ticketRoute?: () => Response) {
  let issued = 0;
  const api = mockApi({
    [TICKET]:
      ticketRoute ??
      (() => {
        issued += 1;
        return json({ ticket: `ticket-${String(issued)}`, expires_in: 30 });
      }),
  });
  const statuses: StreamStatus[] = [];
  const events: StreamEvent[] = [];
  const connection = new StreamConnection({
    onStatus: (status) => statuses.push(status),
    onEvent: (event) => events.push(event),
  });
  return { api, connection, statuses, events };
}

/** Lets pending requests finish and runs the timers due within `ms`. */
const pass = (ms = 0) => vi.advanceTimersByTimeAsync(ms);

async function goLive(connection: StreamConnection, heartbeatSeconds = 30) {
  connection.start();
  await pass();
  FakeSocket.latest.hello(heartbeatSeconds);
  return FakeSocket.latest;
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.install();
  // No jitter: the delay is exactly the ceiling for the attempt.
  vi.spyOn(Math, "random").mockReturnValue(1);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("connecting", () => {
  it("opens the socket with a single-use ticket and is live once the server says hello", async () => {
    const { api, connection, statuses } = setup();

    connection.start();
    await pass();

    expect(FakeSocket.opened).toHaveLength(1);
    expect(FakeSocket.latest.url).toBe("ws://localhost:3000/ws/stream/?ticket=ticket-1");
    expect(statuses).toEqual(["connecting"]);

    FakeSocket.latest.hello();

    expect(statuses).toEqual(["connecting", "live"]);
    expect(api.count(TICKET)).toBe(1);
    connection.stop();
  });

  it("tries again later when a ticket cannot be had", async () => {
    let failing = true;
    const { connection, statuses } = setup(() =>
      failing ? apiError(503, "unavailable", "Down.") : json({ ticket: "t", expires_in: 30 }),
    );

    connection.start();
    await pass();

    expect(FakeSocket.opened).toHaveLength(0);
    expect(statuses).toEqual(["connecting", "offline"]);

    failing = false;
    await pass(1_000);

    expect(FakeSocket.opened).toHaveLength(1);
    connection.stop();
  });

  it("closes the socket and stops retrying when stopped", async () => {
    const { api, connection, statuses } = setup();
    const socket = await goLive(connection);

    connection.stop();
    await pass(120_000);

    expect(socket.closedByClient).toBe(1000);
    expect(statuses.at(-1)).toBe("offline");
    expect(api.count(TICKET)).toBe(1);
    expect(socket.sent).toEqual([]);
  });

  it("does not open a socket for a connection stopped while its ticket was on the way", async () => {
    const { connection } = setup();

    connection.start();
    connection.stop();
    await pass();

    expect(FakeSocket.opened).toHaveLength(0);
  });
});

describe("events", () => {
  it("passes each event on once, however many times it is delivered", async () => {
    const { connection, events } = setup();
    const socket = await goLive(connection);

    socket.event("notification.created", { id: "n-1" }, "event-a");
    socket.event("notification.created", { id: "n-1" }, "event-a");
    socket.event("notification.read", { all: true }, "event-b");

    expect(events.map((event) => [event.type, event.event_id])).toEqual([
      ["notification.created", "event-a"],
      ["notification.read", "event-b"],
    ]);
    connection.stop();
  });

  it("ignores anything that is not an event", async () => {
    const { connection, events, statuses } = setup();
    const socket = await goLive(connection);

    for (const junk of ["not json", "null", "[]", '{"type":"pong"}', '{"event_id":1,"type":"x"}']) {
      socket.serverSends(junk);
    }

    expect(events).toEqual([]);
    expect(statuses.at(-1)).toBe("live");
    connection.stop();
  });
});

describe("staying connected", () => {
  it("pings at the interval the server asked for", async () => {
    const { connection } = setup();
    const socket = await goLive(connection, 10);

    await pass(10_000);
    socket.serverSends({ type: "pong" });
    await pass(10_000);

    expect(socket.sent).toEqual([{ type: "ping" }, { type: "ping" }]);
    connection.stop();
  });

  it("treats a server that stopped answering as gone, and reconnects", async () => {
    const { connection, statuses } = setup();
    const socket = await goLive(connection, 10);

    await pass(30_000); // two pings unanswered; the third beat gives up

    expect(socket.closedByClient).toBe(1000);
    expect(statuses.at(-1)).toBe("offline");

    await pass(1_000);

    expect(FakeSocket.opened).toHaveLength(2);
    connection.stop();
  });

  it("waits longer after each failure, with a new ticket every time, up to a limit", async () => {
    const { api, connection } = setup();
    connection.start();
    await pass();

    const waits: number[] = [];
    for (let attempt = 1; attempt <= 7; attempt += 1) {
      FakeSocket.latest.serverCloses(1006);
      let waited = 0;
      while (FakeSocket.opened.length === attempt) {
        await pass(500);
        waited += 500;
      }
      waits.push(waited);
    }

    expect(waits).toEqual([1_000, 2_000, 4_000, 8_000, 16_000, 30_000, 30_000]);
    expect(api.count(TICKET)).toBe(8);
    expect(new Set(FakeSocket.opened.map((socket) => socket.url)).size).toBe(8);
    connection.stop();
  });

  it("starts from a short wait again after a connection that worked", async () => {
    const { connection } = setup();
    connection.start();
    await pass();
    FakeSocket.latest.serverCloses(1006);
    await pass(1_000);
    FakeSocket.latest.serverCloses(1006);
    await pass(2_000);
    expect(FakeSocket.opened).toHaveLength(3);

    FakeSocket.latest.hello();
    FakeSocket.latest.serverCloses(1006);
    await pass(1_000);

    expect(FakeSocket.opened).toHaveLength(4);
    connection.stop();
  });

  it("reconnects at once when the server ends a working connection for a new ticket", async () => {
    const { connection, statuses } = setup();
    const socket = await goLive(connection);

    socket.serverCloses(4401);
    await pass();

    expect(FakeSocket.opened).toHaveLength(2);
    expect(FakeSocket.latest.url).toContain("ticket=ticket-2");
    expect(statuses).toEqual(["connecting", "live", "connecting"]);
    connection.stop();
  });

  it("does not hammer the server when a ticket is refused outright", async () => {
    const { connection } = setup();
    connection.start();
    await pass();

    FakeSocket.latest.serverCloses(4401);
    await pass(900);

    expect(FakeSocket.opened).toHaveLength(1);
    connection.stop();
  });

  it("retries straight away when the browser comes back online", async () => {
    const { connection } = setup();
    connection.start();
    await pass();
    for (const wait of [1_000, 2_000, 4_000]) {
      FakeSocket.latest.serverCloses(1006);
      await pass(wait);
    }
    FakeSocket.latest.serverCloses(1006); // the next retry is 8 seconds away
    const before = FakeSocket.opened.length;

    window.dispatchEvent(new Event("online"));
    await pass();

    expect(FakeSocket.opened).toHaveLength(before + 1);
    connection.stop();
  });
});
