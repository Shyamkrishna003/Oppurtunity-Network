import { Link } from "react-router";

import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { ApiError } from "../../services/http";
import { useAuditTrail, type AuditEntry, type AuditScope } from "./api";

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

// Where the page of each kind of thing is. Anything else has no page of its own.
const PAGES: Record<string, string> = {
  "users.user": "/users/",
  "organizations.organization": "/organizations/",
  "communities.community": "/communities/",
  "opportunities.opportunity": "/opportunities/",
};

/** "application.status_changed" as words: "Application: status changed". */
function describeAction(action: string): string {
  const [area = "", ...rest] = action.split(".");
  const words = (text: string) => text.replace(/_/g, " ");
  const what = words(rest.join(" "));
  const subject = words(area).replace(/^./, (letter) => letter.toUpperCase());
  return what ? `${subject}: ${what}` : subject;
}

/** The record's extra facts on one line. Only plain values: anything nested is left out. */
function details(metadata: Record<string, unknown>): string {
  return Object.entries(metadata)
    .filter(([, value]) => ["string", "number", "boolean"].includes(typeof value) && value !== "")
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${String(value)}`)
    .join(" · ");
}

function Entry({ entry }: { entry: AuditEntry }) {
  const page = PAGES[entry.target_type];
  const facts = details(entry.metadata);
  return (
    <li className="entry">
      <span>
        <strong>{describeAction(entry.action)}</strong> by{" "}
        {entry.actor ? (
          <Link to={`/users/${entry.actor.id}`}>{entry.actor.display_name}</Link>
        ) : entry.actor_type === "SYSTEM" ? (
          "the system"
        ) : (
          "someone no longer here"
        )}
        {page && (
          <>
            {" · "}
            <Link to={`${page}${entry.target_id}`}>open what it was done to</Link>
          </>
        )}
        {facts && <span className="muted step-note">{facts}</span>}
        {entry.request_id !== undefined && (
          <span className="muted step-note">
            {entry.ip ? `From ${entry.ip} · ` : ""}
            {entry.target_type} {entry.target_id}
          </span>
        )}
      </span>
      <time className="muted" dateTime={entry.created_at}>
        {timeFormat.format(new Date(entry.created_at))}
      </time>
    </li>
  );
}

/** A list of audit records with "show more". Says so plainly when it is not the viewer's
 *  to read. */
export function AuditTrail({ scope, forWhom }: { scope: AuditScope; forWhom: string }) {
  const trail = useAuditTrail(scope);
  const entries = trail.data?.pages.flatMap((page) => page.results) ?? [];

  if (trail.isPending) {
    return (
      <p className="muted" role="status">
        Loading…
      </p>
    );
  }
  if (trail.isError) {
    const denied =
      trail.error instanceof ApiError && (trail.error.status === 403 || trail.error.status === 404);
    return denied ? (
      <p className="muted">This record is for {forWhom}.</p>
    ) : (
      <Notice kind="error">
        <p>{errorMessage(trail.error)}</p>
        <button type="button" onClick={() => void trail.refetch()}>
          Try again
        </button>
      </Notice>
    );
  }
  if (entries.length === 0) {
    return <p className="muted">Nothing has been recorded here.</p>;
  }
  return (
    <>
      <ol className="entry-list">
        {entries.map((entry) => (
          <Entry key={entry.id} entry={entry} />
        ))}
      </ol>
      {trail.hasNextPage && (
        <button
          type="button"
          onClick={() => void trail.fetchNextPage()}
          disabled={trail.isFetchingNextPage}
        >
          {trail.isFetchingNextPage ? "Loading…" : "Show more"}
        </button>
      )}
    </>
  );
}
