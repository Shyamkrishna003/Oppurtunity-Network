import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { Notice } from "../components/Notice";
import { useSessionStatus } from "../features/auth/api";
import { useCommunities, useMyCommunities } from "../features/communities/api";
import {
  JOIN_POLICY_LABELS,
  ROLE_LABELS,
  type Community,
  type MyCommunity,
} from "../features/communities/types";
import { errorMessage } from "../services/formErrors";

function membershipLabel(mine: MyCommunity): string {
  if (mine.status === "INVITED") {
    return "Invited";
  }
  return mine.status === "PENDING" ? "Request pending" : ROLE_LABELS[mine.role];
}

function MyCommunities() {
  const mine = useMyCommunities();
  if (!mine.data || mine.data.length === 0) {
    return null;
  }
  return (
    <section className="card" aria-labelledby="mine-heading">
      <h2 id="mine-heading">Your communities</h2>
      <ul className="entry-list">
        {mine.data.map((item) => (
          <li key={item.community.id} className="entry">
            <Link to={`/communities/${item.community.id}`}>{item.community.name}</Link>
            <span className={item.status === "INVITED" ? "badge badge-ok" : "badge"}>
              {membershipLabel(item)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function CommunityRow({ community }: { community: Community }) {
  const facts = [
    community.category,
    `${community.member_count} ${community.member_count === 1 ? "member" : "members"}`,
    JOIN_POLICY_LABELS[community.join_policy],
    community.visibility === "PRIVATE" && "Private",
  ].filter(Boolean);
  return (
    <li>
      <Link to={`/communities/${community.id}`}>
        <strong>{community.name}</strong>
      </Link>
      {community.is_verified && <span className="badge badge-ok"> Verified</span>}
      <div className="muted">{facts.join(" · ")}</div>
    </li>
  );
}

export function CommunitiesPage() {
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const status = useSessionStatus();
  const communities = useCommunities(query);

  function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget).get("q") ?? "").trim();
    setParams(value ? { q: value } : {});
  }

  const list = communities.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <>
      <div className="page-heading">
        <h1>Communities</h1>
        {status === "authenticated" && (
          <Link to="/communities/new" className="button primary">
            Create community
          </Link>
        )}
      </div>

      {status === "authenticated" && <MyCommunities />}

      <section className="card" aria-labelledby="all-heading">
        <h2 id="all-heading">{query ? `Results for “${query}”` : "All communities"}</h2>
        {/* Keyed by the query so the box follows the URL on back/forward. */}
        <form key={query} role="search" className="search-form" onSubmit={onSearch}>
          <input
            type="search"
            name="q"
            defaultValue={query}
            maxLength={120}
            aria-label="Search communities by name"
            placeholder="Search by name"
          />
          <button type="submit">Search</button>
        </form>

        {communities.isPending && (
          <p className="muted" role="status">
            Loading communities…
          </p>
        )}
        {communities.isError && (
          <Notice kind="error">
            <p>{errorMessage(communities.error)}</p>
            <button type="button" onClick={() => void communities.refetch()}>
              Try again
            </button>
          </Notice>
        )}
        {communities.isSuccess && list.length === 0 && (
          <p className="muted">
            {query ? "No communities match that name." : "No communities yet."}
          </p>
        )}
        {list.length > 0 && (
          <ul className="entry-list">
            {list.map((community) => (
              <CommunityRow key={community.id} community={community} />
            ))}
          </ul>
        )}
        {communities.hasNextPage && (
          <button
            type="button"
            onClick={() => void communities.fetchNextPage()}
            disabled={communities.isFetchingNextPage}
          >
            {communities.isFetchingNextPage ? "Loading…" : "Show more"}
          </button>
        )}
      </section>
    </>
  );
}
