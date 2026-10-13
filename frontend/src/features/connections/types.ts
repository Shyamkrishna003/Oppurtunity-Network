import type { Person } from "../organizations/types";

/**
 * A connection as the viewer sees it. `INCOMING` is a request waiting for the viewer's
 * answer; `OUTGOING` is one the viewer made. A declined request is never reported: to
 * whoever asked it stays `OUTGOING`, and to whoever declined it is gone.
 */
export type ConnectionState = "CONNECTED" | "INCOMING" | "OUTGOING";

export interface Connection {
  id: string;
  state: ConnectionState;
  /** The other person. */
  user: Person;
  created_at: string;
}

/** What stands between the viewer and one person, as shown on that person's profile. */
export interface ConnectionRef {
  id: string;
  state: ConnectionState;
}
