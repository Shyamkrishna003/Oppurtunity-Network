import { useState } from "react";
import { Link } from "react-router";

import { Avatar } from "../../components/Avatar";
import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { formatDate } from "../opportunities/format";
import {
  REGISTRATION_STATUS_LABELS,
  type OpportunityDetail,
  type RegistrationStatus,
} from "../opportunities/types";
import {
  useEventRegistrations,
  useRegistrationSummary,
  useRemoveRegistration,
  useSetRegistrationOpen,
  type Registration,
} from "./api";

const STATUSES = Object.keys(REGISTRATION_STATUS_LABELS) as RegistrationStatus[];

function Row({
  registration,
  onRemove,
  busy,
}: {
  registration: Registration;
  onRemove: () => void;
  busy: boolean;
}) {
  const { person, status } = registration;
  return (
    <li className="entry">
      <div>
        <Link to={`/users/${person.id}`} className="person">
          <Avatar name={person.display_name} url={person.avatar_url} size={32} />
          <strong>{person.display_name}</strong>
        </Link>
        <div className="muted">registered {formatDate(registration.created_at)}</div>
      </div>
      <div className="button-row">
        <span className={status === "CONFIRMED" ? "badge badge-ok" : "badge"}>
          {REGISTRATION_STATUS_LABELS[status]}
        </span>
        {status !== "CANCELLED" && (
          <button type="button" disabled={busy} onClick={onRemove}>
            Remove <span className="visually-hidden">{person.display_name}</span>
          </button>
        )}
      </div>
    </li>
  );
}

/** For the people running a published event: who is coming, and whether more may join. */
export function OrganizerPanel({ opportunity }: { opportunity: OpportunityDetail }) {
  const [status, setStatus] = useState<RegistrationStatus | "">("");
  const summary = useRegistrationSummary(opportunity.id);
  const registrations = useEventRegistrations(opportunity.id, status);
  const setOpen = useSetRegistrationOpen(opportunity.id);
  const remove = useRemoveRegistration(opportunity.id);
  const eventStatus = opportunity.event?.event_status ?? "";
  const list = registrations.data?.pages.flatMap((page) => page.results) ?? [];
  const counts = summary.data?.counts;
  const failure = setOpen.error ?? remove.error;
  const live = opportunity.status === "PUBLISHED";

  return (
    <section className="card" aria-labelledby="registrations-heading">
      <div className="page-heading">
        <h2 id="registrations-heading">Registrations</h2>
        {live && eventStatus === "REGISTRATION_OPEN" && (
          <button type="button" disabled={setOpen.isPending} onClick={() => setOpen.mutate(false)}>
            Close registration
          </button>
        )}
        {live && (eventStatus === "REGISTRATION_CLOSED" || eventStatus === "SCHEDULED") && (
          <button type="button" disabled={setOpen.isPending} onClick={() => setOpen.mutate(true)}>
            Open registration
          </button>
        )}
      </div>
      {failure && <Notice kind="error">{errorMessage(failure)}</Notice>}
      {counts && (
        <p>
          <strong>{counts.CONFIRMED}</strong> going
          {summary.data?.capacity != null && <> of {summary.data.capacity} places</>},{" "}
          <strong>{counts.WAITLISTED}</strong> on the waitlist.
        </p>
      )}

      <div className="field">
        <label htmlFor="registration-filter">Show</label>
        <select
          id="registration-filter"
          value={status}
          onChange={(event) => setStatus(event.target.value as RegistrationStatus | "")}
        >
          <option value="">Everyone</option>
          {STATUSES.map((value) => (
            <option key={value} value={value}>
              {REGISTRATION_STATUS_LABELS[value]}
            </option>
          ))}
        </select>
      </div>

      {registrations.isPending && (
        <p className="muted" role="status">
          Loading…
        </p>
      )}
      {registrations.isError && (
        <Notice kind="error">
          <p>{errorMessage(registrations.error)}</p>
          <button type="button" onClick={() => void registrations.refetch()}>
            Try again
          </button>
        </Notice>
      )}
      {registrations.isSuccess && list.length === 0 && (
        <p className="muted">{status ? "Nobody here." : "Nobody has registered yet."}</p>
      )}
      {list.length > 0 && (
        <ul className="entry-list">
          {list.map((registration) => (
            <Row
              key={registration.id}
              registration={registration}
              busy={remove.isPending}
              onRemove={() => {
                const name = registration.person.display_name;
                if (
                  window.confirm(
                    `Remove ${name}? They are told, and the next person waiting gets the place.`,
                  )
                ) {
                  remove.mutate(registration.id);
                }
              }}
            />
          ))}
        </ul>
      )}
      {registrations.hasNextPage && (
        <button
          type="button"
          onClick={() => void registrations.fetchNextPage()}
          disabled={registrations.isFetchingNextPage}
        >
          {registrations.isFetchingNextPage ? "Loading…" : "Show more"}
        </button>
      )}
    </section>
  );
}
