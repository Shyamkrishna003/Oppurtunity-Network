import { Link, useSearchParams } from "react-router";

import { Notice } from "../components/Notice";
import { useMyApplications } from "../features/applications/api";
import {
  APPLICATION_STATUS_LABELS,
  statusBadgeClass,
  type Application,
  type ApplicationStatus,
} from "../features/applications/types";
import { formatDate } from "../features/opportunities/format";
import { errorMessage } from "../services/formErrors";

const STATUSES = Object.keys(APPLICATION_STATUS_LABELS) as ApplicationStatus[];

function Row({ application }: { application: Application }) {
  const { opportunity } = application;
  const changed = application.status_changed_at !== application.created_at;
  return (
    <li className="entry">
      <div>
        <Link to={`/applications/${application.id}`}>
          <strong>{opportunity.title}</strong>
        </Link>
        <div className="muted">
          {opportunity.organization ? `${opportunity.organization.name} · ` : ""}
          applied {formatDate(application.created_at)}
          {changed && application.status !== "APPLIED"
            ? ` · updated ${formatDate(application.status_changed_at)}`
            : ""}
        </div>
      </div>
      <span className={statusBadgeClass(application.status)}>
        {APPLICATION_STATUS_LABELS[application.status]}
      </span>
    </li>
  );
}

export function ApplicationsPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("status") ?? "";
  // The filter lives in the URL; anything unrecognised there means "all".
  const status = STATUSES.includes(requested as ApplicationStatus)
    ? (requested as ApplicationStatus)
    : "";
  const applications = useMyApplications(status);
  const list = applications.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <>
      <h1>My applications</h1>
      <p className="muted">Every job you have applied to, and where each application stands.</p>

      <section className="card" aria-label="Your applications">
        <div className="field">
          <label htmlFor="status-filter">Show</label>
          <select
            id="status-filter"
            value={status}
            onChange={(event) =>
              setParams(event.target.value ? { status: event.target.value } : {})
            }
          >
            <option value="">All</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {APPLICATION_STATUS_LABELS[value]}
              </option>
            ))}
          </select>
        </div>

        {applications.isPending && (
          <p className="muted" role="status">
            Loading…
          </p>
        )}
        {applications.isError && (
          <Notice kind="error">
            <p>{errorMessage(applications.error)}</p>
            <button type="button" onClick={() => void applications.refetch()}>
              Try again
            </button>
          </Notice>
        )}
        {applications.isSuccess && list.length === 0 && (
          <p className="muted">
            {status ? (
              `Nothing with the status “${APPLICATION_STATUS_LABELS[status]}”.`
            ) : (
              <>
                You have not applied to anything yet. <Link to="/opportunities">Browse jobs</Link>
              </>
            )}
          </p>
        )}
        {list.length > 0 && (
          <ul className="entry-list">
            {list.map((application) => (
              <Row key={application.id} application={application} />
            ))}
          </ul>
        )}
        {applications.hasNextPage && (
          <button
            type="button"
            onClick={() => void applications.fetchNextPage()}
            disabled={applications.isFetchingNextPage}
          >
            {applications.isFetchingNextPage ? "Loading…" : "Show more"}
          </button>
        )}
      </section>
    </>
  );
}
