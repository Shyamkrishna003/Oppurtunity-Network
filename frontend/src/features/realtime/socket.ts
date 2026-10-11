import { http } from "../../services/http";
import type { StreamStatus } from "./realtimeSlice";

/** What the server pushes. `data` is only what this user may see. */
export interface StreamEvent {
  event_id: string;
  type: string;
  occurred_at: string;
  data: Record<string, unknown>;
}

interface Listeners {
  onStatus: (status: StreamStatus) => void;
  onEvent: (event: StreamEvent) => void;
}

// The server closes with this when the ticket is bad, the hourly session cap is reached,
// or the user's session was ended. The answer is always the same: ask for a new ticket.
const CLOSE_UNAUTHENTICATED = 4401;
const BACKOFF_START_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;
const DEFAULT_HEARTBEAT_MS = 30_000;
// The channel layer may deliver an event twice; this many recent IDs are remembered.
const REMEMBERED_EVENTS = 200;

function socketUrl(ticket: string): string {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}/ws/stream/?ticket=${encodeURIComponent(ticket)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStreamEvent(value: unknown): value is StreamEvent {
  return (
    isRecord(value) &&
    typeof value.event_id === "string" &&
    typeof value.type === "string" &&
    isRecord(value.data)
  );
}

/**
 * The one socket this tab keeps open to the server, and everything needed to keep it open.
 *
 * It is a hint, not the record: every event it carries is also available over the API, so
 * a lost event costs nothing as long as the caller refetches when the status turns "live".
 */
export class StreamConnection {
  private socket: WebSocket | null = null;
  private running = false;
  private live = false;
  private failures = 0;
  // Incremented on every connect and stop, so a slow ticket request cannot open a socket
  // for a connection that has since been replaced.
  private generation = 0;
  private lastHeard = 0;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private heartbeatTimer: ReturnType<typeof setInterval> | undefined;
  private readonly seen = new Set<string>();

  constructor(private readonly listeners: Listeners) {}

  start(): void {
    if (this.running) {
      return;
    }
    this.running = true;
    window.addEventListener("online", this.retryNow);
    void this.connect();
  }

  stop(): void {
    if (!this.running) {
      return;
    }
    this.running = false;
    this.generation += 1;
    window.removeEventListener("online", this.retryNow);
    clearTimeout(this.retryTimer);
    this.retryTimer = undefined;
    this.release(1000);
    this.listeners.onStatus("offline");
  }

  private async connect(): Promise<void> {
    const generation = ++this.generation;
    this.listeners.onStatus("connecting");

    let ticket: string;
    try {
      // The access token must not appear in a URL, and a browser cannot set headers on a
      // WebSocket, so the socket is opened with a ticket that works once, for 30 seconds.
      ({ ticket } = await http<{ ticket: string }>("/auth/ws-ticket/", { method: "POST" }));
    } catch {
      // If the session is over, whoever owns it stops this connection; otherwise the
      // server will be back.
      if (generation === this.generation) {
        this.retryLater();
      }
      return;
    }
    if (generation !== this.generation) {
      return;
    }

    const socket = new WebSocket(socketUrl(ticket));
    this.socket = socket;
    socket.onmessage = (message) => {
      this.receive(socket, message.data);
    };
    socket.onclose = (event) => {
      this.closed(socket, event.code);
    };
  }

  private receive(socket: WebSocket, raw: unknown): void {
    if (socket !== this.socket) {
      return;
    }
    this.lastHeard = Date.now();
    let message: unknown;
    try {
      message = JSON.parse(String(raw));
    } catch {
      return;
    }
    if (!isStreamEvent(message)) {
      return; // a heartbeat reply, or something this version does not understand
    }
    if (message.type === "hello") {
      this.live = true;
      this.failures = 0;
      const seconds = Number(message.data.heartbeat_seconds);
      this.beat(socket, seconds > 0 ? seconds * 1000 : DEFAULT_HEARTBEAT_MS);
      this.listeners.onStatus("live");
      return;
    }
    if (this.seen.has(message.event_id)) {
      return;
    }
    this.seen.add(message.event_id);
    if (this.seen.size > REMEMBERED_EVENTS) {
      // A Set keeps insertion order, so the first value is the oldest.
      this.seen.delete(this.seen.values().next().value as string);
    }
    this.listeners.onEvent(message);
  }

  /** Tells the server we are here, and notices when the server no longer is. */
  private beat(socket: WebSocket, intervalMs: number): void {
    clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = setInterval(() => {
      // Two beats without a reply: the connection is dead even though no close arrived
      // (a laptop that slept, a network that changed).
      if (Date.now() - this.lastHeard > intervalMs * 2) {
        this.closed(socket, 0);
        return;
      }
      socket.send(JSON.stringify({ type: "ping" }));
    }, intervalMs);
  }

  private closed(socket: WebSocket, code: number): void {
    if (socket !== this.socket) {
      return;
    }
    const wasLive = this.live;
    this.release(1000);
    if (!this.running) {
      return;
    }
    if (code === CLOSE_UNAUTHENTICATED && wasLive) {
      // Routine: the hourly renewal, or sessions being ended. Getting a new ticket is the
      // check that this tab still has a session. (Refused before the greeting is different:
      // that is a failure, and is retried slowly like any other.)
      void this.connect();
      return;
    }
    this.retryLater();
  }

  private release(code: number): void {
    clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = undefined;
    this.live = false;
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onmessage = null;
      socket.onclose = null;
      socket.close(code);
    }
  }

  private retryLater(): void {
    this.listeners.onStatus("offline");
    const ceiling = Math.min(BACKOFF_MAX_MS, BACKOFF_START_MS * 2 ** this.failures);
    this.failures += 1;
    // Jitter, so that every tab does not come back in the same instant after an outage.
    const delay = ceiling * (0.5 + Math.random() * 0.5);
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      void this.connect();
    }, delay);
  }

  private readonly retryNow = (): void => {
    if (this.retryTimer !== undefined) {
      clearTimeout(this.retryTimer);
      this.retryTimer = undefined;
      void this.connect();
    }
  };
}
