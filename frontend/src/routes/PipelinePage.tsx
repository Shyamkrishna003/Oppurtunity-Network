import { Link, useParams, useSearchParams } from "react-router";

import { Avatar } from "../components/Avatar";
import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useJobApplications, usePipelineSummary } from "../features/applications/api";
import { StageControl } from "../features/applications/StageControl";
import {
  APPLICATION_STATUS_LABELS,
  statusBadgeClass,
  type ApplicationStatus,
  type PipelineApplication,
} from "../features/applications/types";
import { useOpportunity } from "../features/opportunities/api";
import { formatDate } from "../features/opportunities/format";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

const STATUSES = Object.keys(APPLICATION_STATUS_LABELS) as ApplicationStatus[];

function Row({ application }: { application: PipelineApplication }) {
  const { applicant } = application;
  return (
    <li className="entry">
      <div>
        <Link to={`/applications/${application.id}`} className="person">
          <Avatar name={applicant.display_name} url={applicant.avatar_url} size={36} />
          <strong>{applicant.display_name}</strong>
        </Link>
        <div className="muted">
          {application.headline && `${application.headline} · `}
          applied {formatDate(application.created_at)}
        </div>
        {application.referrals.length > 0 && (
          <div>
            <span className="badge badge-ok">Referred</span>{" "}
            <span className="muted">
              by{" "}
              {application.referrals.map((referral) => referral.referrer.display_name).join(", ")}
            </span>
          </div>
        )}
        <span className={statusBadgeClass(application.status)}>
          {APPLICATION_STATUS_LABELS[application.status]}
        </span>
      </div>
      <StageControl
        applicationId={application.id}
        applicantName={applicant.display_name}
        status={application.status}
        nextStatuses={application.next_statuses}
      />
    </li>
  );
}

export function PipelinePage() {
  const { opportunityId = "" } = useParams();
  const [params] = useSearchParams();
  const requested = params.get("status") ?? "";
  // The stage lives in the URL; anything unrecognised there means "all".
  const status = STATUSES.includes(requested as ApplicationStatus)
    ? (requested as ApplicationStatus)
    : "";

  const job = useOpportunity(opportunityId);
  const summary = usePipelineSummary(opportunityId);
  const applications = useJobApplications(opportunityId, status);
  const list = applications.data?.pages.flatMap((page) => page.results) ?? [];

  if (job.isPending || summary.isPending) {
    return <Splash />;
  }
  if (job.isError || summary.isError) {
    const failure = job.error ?? summary.error;
    const denied =
      failure instanceof ApiError && (failure.status === 403 || failure.status === 404);
    return (
      <>
        <h1>{denied ? "Applications not available" : "Something went wrong"}</h1>
        <p className="muted">
          {denied
            ? "This job does not exist, or you are not one of the people who manage it."
            : errorMessage(failure)}
        </p>
      </>
    );
  }

  const { counts, total, openings } = summary.data;
  const filled = job.data.status === "PUBLISHED" && counts.HIRED >= openings;
  const tabs: { key: ApplicationStatus | ""; label: string; count: number }[] = [
    { key: "", label: "All", count: total },
    ...STATUSES.map((key) => ({
      key,
      label: APPLICATION_STATUS_LABELS[key],
      count: counts[key],
    })),
  ];

  return (
    <>
      <h1>Applications</h1>
      <p>
        For <Link to={`/opportunities/${opportunityId}`}>{job.data.title}</Link>
        {job.data.organization && <> at {job.data.organization.name}</>}
      </p>
      {filled && (
        <Notice kind="ok">
          {openings === 1
            ? "The opening is filled."
            : `All ${String(openings)} openings are filled.`}{" "}
          The job is still published and taking applications;{" "}
          <Link to={`/opportunities/${opportunityId}`}>close it</Link> when you are done.
        </Notice>
      )}

      <section className="card" aria-label="Applications to this job">
        <nav aria-label="Stages">
          <ul className="stage-tabs">
            {tabs.map((tab) => (
              <li key={tab.key}>
                <Link
                  to={`/opportunities/${opportunityId}/applications${tab.key ? `?status=${tab.key}` : ""}`}
                  aria-current={tab.key === status ? "page" : undefined}
                >
                  {tab.label} ({tab.count})
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        {applications.isPending && (
          <p className="muted" role="status">
            Loading…
          </p>
        )}
        {applications.isError && (
          <Notice kind="error">
            <p>{errorMessage(applications.error)}</p>
            <button type="button" onClick={() => void applications.refetch()}>
              Try again
            </button>
          </Notice>
        )}
        {applications.isSuccess && list.length === 0 && (
          <p className="muted">
            {status
              ? `No applications with the status “${APPLICATION_STATUS_LABELS[status]}”.`
              : "Nobody has applied yet."}
          </p>
        )}
        {list.length > 0 && (
          <ul className="entry-list">
            {list.map((application) => (
              <Row key={application.id} application={application} />
            ))}
          </ul>
        )}
        {applications.hasNextPage && (
          <button
            type="button"
            onClick={() => void applications.fetchNextPage()}
            disabled={applications.isFetchingNextPage}
          >
            {applications.isFetchingNextPage ? "Loading…" : "Show more"}
          </button>
        )}
      </section>
    </>
  );
}
