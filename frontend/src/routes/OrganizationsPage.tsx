import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { Notice } from "../components/Notice";
import { useSessionStatus } from "../features/auth/api";
import { useMyOrganizations, useOrganizations } from "../features/organizations/api";
import { ROLE_LABELS, type Organization } from "../features/organizations/types";
import { formatLocation } from "../features/profile/labels";
import { errorMessage } from "../services/formErrors";

function MyOrganizations() {
  const mine = useMyOrganizations();
  if (!mine.data || mine.data.length === 0) {
    return null;
  }
  return (
    <section className="card" aria-labelledby="mine-heading">
      <h2 id="mine-heading">Your organizations</h2>
      <ul className="entry-list">
        {mine.data.map(({ organization, role }) => (
          <li key={organization.id} className="entry">
            <Link to={`/organizations/${organization.id}`}>{organization.name}</Link>
            <span className="badge">{ROLE_LABELS[role]}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function OrganizationRow({ organization }: { organization: Organization }) {
  const facts = [
    organization.industry,
    formatLocation(organization),
    `${organization.member_count} ${organization.member_count === 1 ? "member" : "members"}`,
  ].filter(Boolean);
  return (
    <li>
      <Link to={`/organizations/${organization.id}`}>
        <strong>{organization.name}</strong>
      </Link>
      {organization.verification_status === "VERIFIED" && (
        <span className="badge badge-ok"> Verified</span>
      )}
      <div className="muted">{facts.join(" · ")}</div>
    </li>
  );
}

export function OrganizationsPage() {
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const status = useSessionStatus();
  const organizations = useOrganizations(query);

  function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget).get("q") ?? "").trim();
    setParams(value ? { q: value } : {});
  }

  const list = organizations.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <>
      <div className="page-heading">
        <h1>Organizations</h1>
        {status === "authenticated" && (
          <Link to="/organizations/new" className="button primary">
            Create organization
          </Link>
        )}
      </div>

      {status === "authenticated" && <MyOrganizations />}

      <section className="card" aria-labelledby="all-heading">
        <h2 id="all-heading">{query ? `Results for “${query}”` : "All organizations"}</h2>
        {/* Keyed by the query so the box follows the URL on back/forward. */}
        <form key={query} role="search" className="search-form" onSubmit={onSearch}>
          <input
            type="search"
            name="q"
            defaultValue={query}
            maxLength={120}
            aria-label="Search organizations by name"
            placeholder="Search by name"
          />
          <button type="submit">Search</button>
        </form>

        {organizations.isPending && (
          <p className="muted" role="status">
            Loading organizations…
          </p>
        )}
        {organizations.isError && (
          <Notice kind="error">
            <p>{errorMessage(organizations.error)}</p>
            <button type="button" onClick={() => void organizations.refetch()}>
              Try again
            </button>
          </Notice>
        )}
        {organizations.isSuccess && list.length === 0 && (
          <p className="muted">
            {query ? "No organizations match that name." : "No organizations yet."}
          </p>
        )}
        {list.length > 0 && (
          <ul className="entry-list">
            {list.map((organization) => (
              <OrganizationRow key={organization.id} organization={organization} />
            ))}
          </ul>
        )}
        {organizations.hasNextPage && (
          <button
            type="button"
            onClick={() => void organizations.fetchNextPage()}
            disabled={organizations.isFetchingNextPage}
          >
            {organizations.isFetchingNextPage ? "Loading…" : "Show more"}
          </button>
        )}
      </section>
    </>
  );
}
