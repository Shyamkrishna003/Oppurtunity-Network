import { Link, useSearchParams } from "react-router";

import { Notice } from "../components/Notice";
import { useMe, useSessionStatus } from "../features/auth/api";
import { useFeed } from "../features/opportunities/api";
import { FeedFilters } from "../features/opportunities/FeedFilters";
import { feedSearch } from "../features/opportunities/feedParams";
import { MatchReasons } from "../features/opportunities/MatchReasons";
import { OpportunityCard } from "../features/opportunities/OpportunityCard";
import { SaveButton } from "../features/opportunities/SaveButton";
import { errorMessage } from "../services/formErrors";

export function OpportunitiesPage() {
  const [params, setParams] = useSearchParams();
  const status = useSessionStatus();
  const me = useMe();
  const signedIn = status === "authenticated";
  const feed = useFeed(feedSearch(params));

  function change(changes: Record<string, string | string[] | null>) {
    const next = new URLSearchParams(params);
    for (const [name, value] of Object.entries(changes)) {
      next.delete(name);
      for (const item of Array.isArray(value) ? value : [value]) {
        if (item) {
          next.append(name, item);
        }
      }
    }
    setParams(next);
  }

  const results = feed.data?.pages.flatMap((page) => page.results) ?? [];
  const sortedByMatch = (params.get("sort") ?? (params.get("q") ? "relevant" : "")) === "relevant";
  // "Best match" can only reflect a profile that says something.
  const emptyProfile =
    me.data !== undefined &&
    me.data.skills.has.length === 0 &&
    me.data.skills.interested.length === 0 &&
    !me.data.profile.city &&
    !me.data.profile.work_mode_preference;

  return (
    <>
      <div className="page-heading">
        <h1>Opportunities</h1>
        {signedIn && (
          <div className="button-row">
            <Link to="/saved" className="button">
              Saved
            </Link>
            <Link to="/opportunities/new" className="button primary">
              Post a job
            </Link>
          </div>
        )}
      </div>

      <FeedFilters
        params={params}
        onChange={change}
        onClear={() => setParams({})}
        signedIn={signedIn}
      />

      {signedIn && sortedByMatch && emptyProfile && (
        <Notice kind="ok">
          Results are ordered by how well they match your profile, and yours is still empty.{" "}
          <Link to="/settings/profile">Add your skills, location and work preference</Link> to see
          the best matches first.
        </Notice>
      )}
      {!signedIn && status === "anonymous" && (
        <p className="muted">
          <Link to="/login?next=%2Fopportunities">Sign in</Link> to save opportunities and see which
          ones match your skills.
        </p>
      )}

      <section className="card" aria-labelledby="results-heading">
        <h2 id="results-heading" className="visually-hidden">
          Results
        </h2>
        {feed.isPending && (
          <p className="muted" role="status">
            Loading opportunities…
          </p>
        )}
        {feed.isError && (
          <Notice kind="error">
            <p>{errorMessage(feed.error)}</p>
            <button type="button" onClick={() => void feed.refetch()}>
              Try again
            </button>
          </Notice>
        )}
        {feed.isSuccess && results.length === 0 && (
          <p className="muted">
            {feedSearch(params).replace(/(^|&)sort=[a-z]+/, "")
              ? "Nothing matches these filters. Try removing some."
              : "No opportunities have been published yet."}
          </p>
        )}
        {results.length > 0 && (
          <ul className="entry-list">
            {results.map((item) => (
              <OpportunityCard
                key={item.id}
                opportunity={item}
                actions={<SaveButton id={item.id} title={item.title} saved={item.is_saved} />}
              >
                <MatchReasons match={item.match} />
              </OpportunityCard>
            ))}
          </ul>
        )}
        {feed.hasNextPage && (
          <button
            type="button"
            onClick={() => void feed.fetchNextPage()}
            disabled={feed.isFetchingNextPage}
          >
            {feed.isFetchingNextPage ? "Loading…" : "Show more"}
          </button>
        )}
      </section>
    </>
  );
}
