import { Link, useParams, useSearchParams } from "react-router";

import { Notice } from "../components/Notice";
import {
  CATEGORY_LABELS,
  REPORT_STATUS_LABELS,
  useCommunityReports,
  type CommunityReport,
  type ReportStatus,
} from "../features/moderation/api";
import { formatDate } from "../features/opportunities/format";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

const STATUSES = Object.keys(REPORT_STATUS_LABELS) as ReportStatus[];

function Row({ communityId, report }: { communityId: string; report: CommunityReport }) {
  const waiting = report.status === "OPEN" || report.status === "UNDER_REVIEW";
  return (
    <li className="entry">
      <div>
        <Link to={`/communities/${communityId}/reports/${report.id}`}>
          <strong>{report.target.name}</strong>
        </Link>
        <div className="muted">
          {CATEGORY_LABELS[report.category]} · reported {formatDate(report.created_at)}
        </div>
        {report.assigned_to && <div className="muted">With {report.assigned_to.display_name}</div>}
      </div>
      <span className={waiting ? "badge badge-error" : "badge"}>
        {REPORT_STATUS_LABELS[report.status]}
      </span>
    </li>
  );
}

/** Reports members sent to this community's moderators. */
export function CommunityReportsPage() {
  const { communityId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  // Which reports are shown lives in the address. With nothing chosen: the ones waiting.
  const requested = params.get("status") ?? "OPEN";
  const status =
    requested === "ALL" ? "" : STATUSES.includes(requested as ReportStatus) ? requested : "OPEN";
  const queue = useCommunityReports(communityId, status as ReportStatus | "");
  const list = queue.data?.pages.flatMap((page) => page.results) ?? [];
  const denied =
    queue.error instanceof ApiError && (queue.error.status === 403 || queue.error.status === 404);

  const back = (
    <p>
      <Link to={`/communities/${communityId}`}>Back to the community</Link>
    </p>
  );
  if (denied) {
    return (
      <>
        {back}
        <h1>Reports</h1>
        <p className="muted">This page is for the community&apos;s moderators.</p>
      </>
    );
  }
  return (
    <>
      {back}
      <h1>Reports</h1>
      <p className="muted">
        What members reported to this community&apos;s moderators, the longest-waiting first. Who
        reported is not shown.
      </p>
      <section className="card" aria-label="Reports">
        <div className="field">
          <label htmlFor="report-status">Show</label>
          <select
            id="report-status"
            value={status || "ALL"}
            onChange={(event) =>
              setParams(event.target.value === "OPEN" ? {} : { status: event.target.value })
            }
          >
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {REPORT_STATUS_LABELS[value]}
              </option>
            ))}
            <option value="ALL">All reports</option>
          </select>
        </div>

        {queue.isPending && (
          <p className="muted" role="status">
            Loading…
          </p>
        )}
        {queue.isError && (
          <Notice kind="error">
            <p>{errorMessage(queue.error)}</p>
            <button type="button" onClick={() => void queue.refetch()}>
              Try again
            </button>
          </Notice>
        )}
        {queue.isSuccess && list.length === 0 && (
          <p className="muted">
            {status === "OPEN" ? "Nothing is waiting. Well done." : "No reports here."}
          </p>
        )}
        {list.length > 0 && (
          <ul className="entry-list">
            {list.map((report) => (
              <Row key={report.id} communityId={communityId} report={report} />
            ))}
          </ul>
        )}
        {queue.hasNextPage && (
          <button
            type="button"
            onClick={() => void queue.fetchNextPage()}
            disabled={queue.isFetchingNextPage}
          >
            {queue.isFetchingNextPage ? "Loading…" : "Show more"}
          </button>
        )}
      </section>
    </>
  );
}
