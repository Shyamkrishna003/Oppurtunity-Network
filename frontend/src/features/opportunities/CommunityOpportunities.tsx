import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { useCommunityOpportunities, useSubmissionAction, useSubmissions } from "./api";
import { OpportunityCard } from "./OpportunityCard";
import type { CommunityOpportunity } from "./types";

interface Props {
  communityId: string;
  /** Whether the viewer decides what this community shows (moderator, admin or owner). */
  canReview: boolean;
}

function ReviewerActions({
  communityId,
  item,
}: {
  communityId: string;
  item: CommunityOpportunity;
}) {
  const act = useSubmissionAction(communityId);
  const title = item.opportunity.title;
  return (
    <>
      <button
        type="button"
        disabled={act.isPending}
        onClick={() =>
          act.mutate({ shareId: item.share_id, action: item.is_featured ? "unfeature" : "feature" })
        }
      >
        {item.is_featured ? "Unpin" : "Pin to top"} <span className="visually-hidden">{title}</span>
      </button>
      <button
        type="button"
        disabled={act.isPending}
        onClick={() => {
          if (window.confirm(`Remove “${title}” from this community? This cannot be undone.`)) {
            act.mutate({ shareId: item.share_id, action: "remove" });
          }
        }}
      >
        Remove <span className="visually-hidden">{title}</span>
      </button>
    </>
  );
}

/** The opportunities a community shows: pinned ones first, then the rest, newest first. */
export function CommunityOpportunityList({ communityId, canReview }: Props) {
  const featured = useCommunityOpportunities(communityId, true);
  const all = useCommunityOpportunities(communityId, false);

  if (all.isPending) {
    return (
      <p className="muted" role="status">
        Loading opportunities…
      </p>
    );
  }
  if (all.isError) {
    return (
      <Notice kind="error">
        <p>{errorMessage(all.error)}</p>
        <button type="button" onClick={() => void all.refetch()}>
          Try again
        </button>
      </Notice>
    );
  }

  const pinned = featured.data?.pages.flatMap((page) => page.results) ?? [];
  const pinnedIds = new Set(pinned.map((item) => item.share_id));
  const rest = all.data.pages
    .flatMap((page) => page.results)
    .filter((item) => !pinnedIds.has(item.share_id));
  if (pinned.length === 0 && rest.length === 0) {
    return <p className="muted">No open opportunities here yet.</p>;
  }

  const card = (item: CommunityOpportunity) => (
    <OpportunityCard
      key={item.share_id}
      opportunity={item.opportunity}
      badge={item.is_featured ? <span className="badge badge-ok"> Featured</span> : undefined}
      actions={canReview ? <ReviewerActions communityId={communityId} item={item} /> : undefined}
    />
  );
  return (
    <>
      <ul className="entry-list">
        {pinned.map(card)}
        {rest.map(card)}
      </ul>
      {all.hasNextPage && (
        <button
          type="button"
          onClick={() => void all.fetchNextPage()}
          disabled={all.isFetchingNextPage}
        >
          {all.isFetchingNextPage ? "Loading…" : "Show more"}
        </button>
      )}
    </>
  );
}

/** Opportunities waiting for the community's decision. Render for reviewers only. */
export function ReviewQueue({ communityId }: { communityId: string }) {
  const queue = useSubmissions(communityId);
  const act = useSubmissionAction(communityId);

  if (queue.isPending) {
    return (
      <p className="muted" role="status">
        Loading…
      </p>
    );
  }
  if (queue.isError) {
    return (
      <Notice kind="error">
        <p>{errorMessage(queue.error)}</p>
        <button type="button" onClick={() => void queue.refetch()}>
          Try again
        </button>
      </Notice>
    );
  }

  const list = queue.data.pages.flatMap((page) => page.results);
  if (list.length === 0) {
    return <p className="muted">Nothing is waiting for review.</p>;
  }
  return (
    <>
      {act.isError && <Notice kind="error">{errorMessage(act.error)}</Notice>}
      <ul className="entry-list">
        {list.map((item) => (
          <OpportunityCard
            key={item.id}
            opportunity={item.opportunity}
            badge={
              item.submitted_by ? (
                <span className="muted"> · shared by {item.submitted_by.display_name}</span>
              ) : undefined
            }
            actions={
              <>
                <button
                  type="button"
                  className="primary"
                  disabled={act.isPending}
                  onClick={() => act.mutate({ shareId: item.id, action: "approve" })}
                >
                  Approve <span className="visually-hidden">{item.opportunity.title}</span>
                </button>
                <button
                  type="button"
                  disabled={act.isPending}
                  onClick={() => {
                    // Cancel leaves it in the queue; an empty reason is allowed.
                    const reason = window.prompt("Reason for rejecting (shown to the poster):", "");
                    if (reason !== null) {
                      act.mutate({ shareId: item.id, action: "reject", reason: reason.trim() });
                    }
                  }}
                >
                  Reject <span className="visually-hidden">{item.opportunity.title}</span>
                </button>
              </>
            }
          />
        ))}
      </ul>
      {queue.hasNextPage && (
        <button
          type="button"
          onClick={() => void queue.fetchNextPage()}
          disabled={queue.isFetchingNextPage}
        >
          Show more
        </button>
      )}
    </>
  );
}
