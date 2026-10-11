import { vi } from "vitest";

let nextEventId = 0;

/** Stands in for the browser's WebSocket; the test plays the server. */
export class FakeSocket {
  static opened: FakeSocket[] = [];

  /** Replaces the global WebSocket until `vi.unstubAllGlobals()`. */
  static install(): void {
    FakeSocket.opened = [];
    vi.stubGlobal("WebSocket", FakeSocket);
  }

  static get latest(): FakeSocket {
    const socket = FakeSocket.opened.at(-1);
    if (!socket) {
      throw new Error("No socket has been opened.");
    }
    return socket;
  }

  onmessage: ((message: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  readonly sent: unknown[] = [];
  /** The code the client closed with, if it did. */
  closedByClient: number | null = null;

  constructor(readonly url: string) {
    FakeSocket.opened.push(this);
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }

  close(code = 1000): void {
    this.closedByClient ??= code;
  }

  serverSends(message: unknown): void {
    this.onmessage?.({ data: typeof message === "string" ? message : JSON.stringify(message) });
  }

  serverCloses(code: number): void {
    this.onclose?.({ code });
  }

  event(type: string, data: Record<string, unknown> = {}, eventId?: string): void {
    nextEventId += 1;
    this.serverSends({
      event_id: eventId ?? `event-${String(nextEventId)}`,
      type,
      occurred_at: "2026-10-11T09:00:00Z",
      data,
    });
  }

  hello(heartbeatSeconds = 30): void {
    this.event("hello", { heartbeat_seconds: heartbeatSeconds });
  }
}
