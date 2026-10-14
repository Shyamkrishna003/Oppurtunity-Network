import { Link } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { usePlatformTotals } from "../features/admin/api";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

const timeFormat = new Intl.DateTimeFormat(undefined, { timeStyle: "short" });
const number = new Intl.NumberFormat();

function Figures({ title, figures }: { title: string; figures: [label: string, value: number][] }) {
  const id = `figures-${title.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <section className="card" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      <dl className="figures">
        {figures.map(([label, value]) => (
          <div key={label} className="figure">
            <dt>{label}</dt>
            <dd>{number.format(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** The platform at a glance, for its admins. */
export function AdminPage() {
  const totals = usePlatformTotals();

  if (totals.isPending) {
    return <Splash />;
  }
  if (totals.isError) {
    const denied = totals.error instanceof ApiError && totals.error.status === 403;
    return (
      <>
        <h1>Admin</h1>
        {denied ? (
          <p className="muted">This page is for the platform&apos;s admins.</p>
        ) : (
          <Notice kind="error">
            <p>{errorMessage(totals.error)}</p>
            <button type="button" onClick={() => void totals.refetch()}>
              Try again
            </button>
          </Notice>
        )}
      </>
    );
  }

  const { users, organizations, communities, opportunities, outcomes, reports } = totals.data;
  const waiting = reports.waiting + reports.under_review;
  return (
    <>
      <div className="page-heading">
        <h1>Admin</h1>
        <button type="button" onClick={() => void totals.refetch()} disabled={totals.isFetching}>
          {totals.isFetching ? "Counting…" : "Count again"}
        </button>
      </div>
      <p className="muted">
        Counted at {timeFormat.format(new Date(totals.data.generated_at))}. “Recently” means in the
        last seven days.
      </p>
      <p>
        <Link to="/moderation">
          {waiting === 0
            ? "No reports are waiting"
            : `${number.format(waiting)} ${waiting === 1 ? "report is" : "reports are"} waiting`}
        </Link>
        {" · "}
        <Link to="/admin/audit">Audit log</Link>
      </p>

      <Figures
        title="Outcomes"
        figures={[
          ["Applications", outcomes.applications],
          ["Hires", outcomes.hires],
          ["Event places held", outcomes.registrations],
          ["Came to an event", outcomes.attendances],
          ["Referrals made", outcomes.referrals],
          ["Joined through a referral", outcomes.referral_joins],
        ]}
      />
      <Figures
        title="Opportunities"
        figures={[
          ["Open to find now", opportunities.published],
          ["Jobs", opportunities.jobs],
          ["Events", opportunities.events],
          ["Published recently", opportunities.published_recently],
          ["Hidden or removed", opportunities.hidden_or_removed],
        ]}
      />
      <Figures
        title="People and places"
        figures={[
          ["People", users.total],
          ["Confirmed their email", users.verified],
          ["Joined recently", users.joined_recently],
          ["Suspended now", users.suspended],
          ["Organizations", organizations.total],
          ["Verified organizations", organizations.verified],
          ["Communities", communities.total],
        ]}
      />
      <Figures
        title="Reports"
        figures={[
          ["Waiting", reports.waiting],
          ["Under review", reports.under_review],
        ]}
      />
    </>
  );
}
