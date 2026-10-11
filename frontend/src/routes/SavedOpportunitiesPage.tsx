import { Link } from "react-router";

import { Notice } from "../components/Notice";
import { useSavedOpportunities } from "../features/opportunities/api";
import { formatDate } from "../features/opportunities/format";
import { OpportunityCard } from "../features/opportunities/OpportunityCard";
import { SaveButton } from "../features/opportunities/SaveButton";
import { STATUS_LABELS } from "../features/opportunities/types";
import { errorMessage } from "../services/formErrors";

export function SavedOpportunitiesPage() {
  const saved = useSavedOpportunities();
  const list = saved.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <>
      <h1>Saved opportunities</h1>
      <p className="muted">
        Most recently saved first. Ones that have closed since stay here until you remove them.
      </p>
      <section className="card" aria-label="Saved opportunities">
        {saved.isPending && (
          <p className="muted" role="status">
            Loading…
          </p>
        )}
        {saved.isError && (
          <Notice kind="error">
            <p>{errorMessage(saved.error)}</p>
            <button type="button" onClick={() => void saved.refetch()}>
              Try again
            </button>
          </Notice>
        )}
        {saved.isSuccess && list.length === 0 && (
          <p className="muted">
            Nothing saved yet. <Link to="/opportunities">Browse opportunities</Link> and press Save
            on the ones you want to come back to.
          </p>
        )}
        {list.length > 0 && (
          <ul className="entry-list">
            {list.map(({ opportunity, saved_at: savedAt }) => (
              <OpportunityCard
                key={opportunity.id}
                opportunity={opportunity}
                badge={
                  opportunity.status === "PUBLISHED" ? undefined : (
                    <span className="badge"> {STATUS_LABELS[opportunity.status]}</span>
                  )
                }
                actions={<SaveButton id={opportunity.id} title={opportunity.title} saved />}
              >
                <p className="muted">Saved {formatDate(savedAt)}</p>
              </OpportunityCard>
            ))}
          </ul>
        )}
        {saved.hasNextPage && (
          <button
            type="button"
            onClick={() => void saved.fetchNextPage()}
            disabled={saved.isFetchingNextPage}
          >
            {saved.isFetchingNextPage ? "Loading…" : "Show more"}
          </button>
        )}
      </section>
    </>
  );
}
