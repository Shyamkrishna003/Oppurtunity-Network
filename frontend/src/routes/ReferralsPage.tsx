import { Link, useSearchParams } from "react-router";

import { Notice } from "../components/Notice";
import { formatDate } from "../features/opportunities/format";
import { useReferrals, type ReferralRole } from "../features/referrals/api";
import {
  REFERRAL_STATUS_LABELS,
  referralBadgeClass,
  type Referral,
} from "../features/referrals/types";
import { errorMessage } from "../services/formErrors";

interface Tab {
  /** The value of `?show=` that selects this list. */
  show: string;
  role: ReferralRole;
  label: string;
  empty: string;
}

/** The list shown when the URL asks for nothing in particular. */
const SENT: Tab = {
  show: "",
  role: "requester",
  label: "Asked by me",
  empty:
    "You have not asked anyone for a referral yet. Open a job at an organization where one of your connections works, and ask from there.",
};
const TABS: Tab[] = [
  SENT,
  {
    show: "received",
    role: "referrer",
    label: "Asked of me",
    empty: "Nobody has asked you for a referral.",
  },
];

function Row({ referral, role }: { referral: Referral; role: ReferralRole }) {
  const { opportunity } = referral;
  const other = role === "requester" ? referral.referrer : referral.requester;
  return (
    <li className="entry">
      <div>
        <Link to={`/referrals/${referral.id}`}>
          <strong>{opportunity.title}</strong>
        </Link>
        <div className="muted">
          {opportunity.organization ? `${opportunity.organization.name} · ` : ""}
          {role === "requester" ? "asked" : "asked by"} {other.display_name} ·{" "}
          {formatDate(referral.created_at)}
        </div>
      </div>
      <span className={referralBadgeClass(referral.status)}>
        {REFERRAL_STATUS_LABELS[referral.status]}
      </span>
    </li>
  );
}

export function ReferralsPage() {
  const [params] = useSearchParams();
  // Which list is shown lives in the URL; anything unrecognised there means the first.
  const tab = TABS.find((candidate) => candidate.show === params.get("show")) ?? SENT;
  const referrals = useReferrals(tab.role);
  const list = referrals.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <>
      <h1>Referrals</h1>
      <p className="muted">
        Requests between you and your connections, and how each referral turned out.
      </p>

      <section className="card" aria-label="Your referrals">
        <nav aria-label="Show">
          <ul className="stage-tabs">
            {TABS.map((candidate) => (
              <li key={candidate.role}>
                <Link
                  to={candidate.show ? `/referrals?show=${candidate.show}` : "/referrals"}
                  aria-current={candidate === tab ? "page" : undefined}
                >
                  {candidate.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        {referrals.isPending && (
          <p className="muted" role="status">
            Loading…
          </p>
        )}
        {referrals.isError && (
          <Notice kind="error">
            <p>{errorMessage(referrals.error)}</p>
            <button type="button" onClick={() => void referrals.refetch()}>
              Try again
            </button>
          </Notice>
        )}
        {referrals.isSuccess && list.length === 0 && <p className="muted">{tab.empty}</p>}
        {list.length > 0 && (
          <ul className="entry-list">
            {list.map((referral) => (
              <Row key={referral.id} referral={referral} role={tab.role} />
            ))}
          </ul>
        )}
        {referrals.hasNextPage && (
          <button
            type="button"
            onClick={() => void referrals.fetchNextPage()}
            disabled={referrals.isFetchingNextPage}
          >
            {referrals.isFetchingNextPage ? "Loading…" : "Show more"}
          </button>
        )}
      </section>
    </>
  );
}
