import { Link, useSearchParams } from "react-router";

import { Avatar } from "../components/Avatar";
import { Notice } from "../components/Notice";
import { useConnections, useIncomingCount } from "../features/connections/api";
import { ConnectionActions } from "../features/connections/ConnectionActions";
import type { Connection, ConnectionState } from "../features/connections/types";
import { formatDate } from "../features/opportunities/format";
import { errorMessage } from "../services/formErrors";

interface Tab {
  /** The value of `?show=` that selects this list. */
  show: string;
  state: ConnectionState;
  label: string;
}

/** The list shown when the URL asks for nothing in particular. */
const CONNECTED: Tab = { show: "", state: "CONNECTED", label: "Connections" };
const TABS: Tab[] = [
  CONNECTED,
  { show: "requests", state: "INCOMING", label: "Requests" },
  { show: "sent", state: "OUTGOING", label: "Sent" },
];

const EMPTY: Record<ConnectionState, string> = {
  CONNECTED:
    "You have no connections yet. Open someone's profile and ask to connect: connections are who you can ask for a referral.",
  INCOMING: "Nobody is waiting for your answer.",
  OUTGOING: "You have no requests waiting for an answer.",
};

const DATED: Record<ConnectionState, string> = {
  CONNECTED: "since",
  INCOMING: "asked",
  OUTGOING: "asked",
};

function Row({ connection }: { connection: Connection }) {
  const { user } = connection;
  return (
    <li className="entry">
      <span className="person">
        <Avatar name={user.display_name} url={user.avatar_url} size={36} />
        <span>
          <Link to={`/users/${user.id}`}>{user.display_name}</Link>
          {user.headline && <span className="muted"> · {user.headline}</span>}
          <span className="muted">
            {" "}
            · {DATED[connection.state]} {formatDate(connection.created_at)}
          </span>
        </span>
      </span>
      <ConnectionActions userId={user.id} name={user.display_name} connection={connection} />
    </li>
  );
}

export function ConnectionsPage() {
  const [params] = useSearchParams();
  // Which list is shown lives in the URL; anything unrecognised there means the first.
  const tab = TABS.find((candidate) => candidate.show === params.get("show")) ?? CONNECTED;
  const connections = useConnections(tab.state);
  const incoming = useIncomingCount();
  const list = connections.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <>
      <h1>Connections</h1>
      <p className="muted">
        People you know here. Only you can see this list; nobody can browse your connections.
      </p>

      <section className="card" aria-label="Your connections">
        <nav aria-label="Show">
          <ul className="stage-tabs">
            {TABS.map((candidate) => (
              <li key={candidate.state}>
                <Link
                  to={candidate.show ? `/connections?show=${candidate.show}` : "/connections"}
                  aria-current={candidate === tab ? "page" : undefined}
                >
                  {candidate.label}
                  {candidate.state === "INCOMING" && incoming.data ? ` (${incoming.data})` : ""}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        {connections.isPending && (
          <p className="muted" role="status">
            Loading…
          </p>
        )}
        {connections.isError && (
          <Notice kind="error">
            <p>{errorMessage(connections.error)}</p>
            <button type="button" onClick={() => void connections.refetch()}>
              Try again
            </button>
          </Notice>
        )}
        {connections.isSuccess && list.length === 0 && <p className="muted">{EMPTY[tab.state]}</p>}
        {list.length > 0 && (
          <ul className="entry-list">
            {list.map((connection) => (
              <Row key={connection.id} connection={connection} />
            ))}
          </ul>
        )}
        {connections.hasNextPage && (
          <button
            type="button"
            onClick={() => void connections.fetchNextPage()}
            disabled={connections.isFetchingNextPage}
          >
            {connections.isFetchingNextPage ? "Loading…" : "Show more"}
          </button>
        )}
      </section>
    </>
  );
}
