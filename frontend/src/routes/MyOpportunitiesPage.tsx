import { Link, useSearchParams } from "react-router";

import { Notice } from "../components/Notice";
import { useMyOpportunities } from "../features/opportunities/api";
import { formatDate } from "../features/opportunities/format";
import {
  STATUS_LABELS,
  type Opportunity,
  type OpportunityStatus,
} from "../features/opportunities/types";
import { errorMessage } from "../services/formErrors";

const STATUSES = Object.keys(STATUS_LABELS) as OpportunityStatus[];

function Row({ opportunity }: { opportunity: Opportunity }) {
  const owner = opportunity.organization ? opportunity.organization.name : "Personal";
  const when = opportunity.published_at
    ? `published ${formatDate(opportunity.published_at)}`
    : `created ${formatDate(opportunity.created_at)}`;
  return (
    <li className="entry">
      <div>
        <Link to={`/opportunities/${opportunity.id}`}>
          <strong>{opportunity.title}</strong>
        </Link>
        <div className="muted">
          {owner} · {when}
          {opportunity.deadline && ` · apply by ${formatDate(opportunity.deadline)}`}
        </div>
      </div>
      <span className={opportunity.status === "PUBLISHED" ? "badge badge-ok" : "badge"}>
        {STATUS_LABELS[opportunity.status]}
      </span>
    </li>
  );
}

export function MyOpportunitiesPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("status") ?? "";
  // The filter lives in the URL; anything unrecognised there means "all".
  const status = STATUSES.includes(requested as OpportunityStatus)
    ? (requested as OpportunityStatus)
    : "";
  const opportunities = useMyOpportunities(status);
  const list = opportunities.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <>
      <div className="page-heading">
        <h1>My opportunities</h1>
        <Link to="/opportunities/new" className="button primary">
          Post a job
        </Link>
      </div>
      <p className="muted">
        Everything you manage: your own, and those of organizations where you are an owner, admin or
        recruiter.
      </p>

      <section className="card" aria-label="Opportunities you manage">
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
                {STATUS_LABELS[value]}
              </option>
            ))}
          </select>
        </div>

        {opportunities.isPending && (
          <p className="muted" role="status">
            Loading…
          </p>
        )}
        {opportunities.isError && (
          <Notice kind="error">
            <p>{errorMessage(opportunities.error)}</p>
            <button type="button" onClick={() => void opportunities.refetch()}>
              Try again
            </button>
          </Notice>
        )}
        {opportunities.isSuccess && list.length === 0 && (
          <p className="muted">
            {status
              ? `Nothing with the status “${STATUS_LABELS[status]}”.`
              : "You have not posted anything yet."}
          </p>
        )}
        {list.length > 0 && (
          <ul className="entry-list">
            {list.map((opportunity) => (
              <Row key={opportunity.id} opportunity={opportunity} />
            ))}
          </ul>
        )}
        {opportunities.hasNextPage && (
          <button
            type="button"
            onClick={() => void opportunities.fetchNextPage()}
            disabled={opportunities.isFetchingNextPage}
          >
            {opportunities.isFetchingNextPage ? "Loading…" : "Show more"}
          </button>
        )}
      </section>
    </>
  );
}
