import { Link } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import {
  CATEGORY_LABELS,
  REPORT_STATUS_LABELS,
  TARGET_LABELS,
  useMyReports,
  type MyReport,
} from "../features/moderation/api";
import { formatDate } from "../features/opportunities/format";
import { errorMessage } from "../services/formErrors";

function Row({ report }: { report: MyReport }) {
  const decided = report.status === "ACTION_TAKEN" || report.status === "DISMISSED";
  return (
    <li className="entry">
      <div>
        <Link to={report.target.url}>
          <strong>{report.target.name}</strong>
        </Link>
        <div className="muted">
          {TARGET_LABELS[report.target.type]} · {CATEGORY_LABELS[report.category]} · reported{" "}
          {formatDate(report.created_at)}
        </div>
      </div>
      {/* Only whether it has been looked at: what was decided about someone else is not
          the reporter's to know. */}
      <span className={decided ? "badge badge-ok" : "badge"}>
        {decided ? "Reviewed" : REPORT_STATUS_LABELS[report.status]}
      </span>
    </li>
  );
}

export function MyReportsPage() {
  const reports = useMyReports();
  const list = reports.data?.pages.flatMap((page) => page.results) ?? [];

  if (reports.isPending) {
    return <Splash />;
  }
  return (
    <>
      <h1>My reports</h1>
      <p className="muted">
        What you have reported to the moderators. You are told when a report has been reviewed, but
        not what was decided about someone else.
      </p>
      <section className="card" aria-label="Your reports">
        {reports.isError && (
          <Notice kind="error">
            <p>{errorMessage(reports.error)}</p>
            <button type="button" onClick={() => void reports.refetch()}>
              Try again
            </button>
          </Notice>
        )}
        {reports.isSuccess && list.length === 0 && (
          <p className="muted">You have not reported anything.</p>
        )}
        {list.length > 0 && (
          <ul className="entry-list">
            {list.map((report) => (
              <Row key={report.id} report={report} />
            ))}
          </ul>
        )}
        {reports.hasNextPage && (
          <button
            type="button"
            onClick={() => void reports.fetchNextPage()}
            disabled={reports.isFetchingNextPage}
          >
            {reports.isFetchingNextPage ? "Loading…" : "Show more"}
          </button>
        )}
      </section>
    </>
  );
}
