import { Link, useParams } from "react-router";

import { Avatar } from "../components/Avatar";
import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useApplication, useDownloadResume, useWithdraw } from "../features/applications/api";
import { StageControl } from "../features/applications/StageControl";
import {
  APPLICATION_STATUS_LABELS,
  statusBadgeClass,
  type ApplicationDetail,
  type ApplicationStep,
} from "../features/applications/types";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function stepText(step: ApplicationStep): string {
  if (step.from_status === "") {
    return "Application sent";
  }
  if (step.to_status === "WITHDRAWN") {
    return "Withdrawn by the applicant";
  }
  return `Moved to ${APPLICATION_STATUS_LABELS[step.to_status]}`;
}

function Actions({ application }: { application: ApplicationDetail }) {
  const withdraw = useWithdraw(application.id);
  const download = useDownloadResume(application.id);
  const { viewer } = application;
  const failure = withdraw.error ?? download.error;

  if (!viewer.can_withdraw && !viewer.can_download_resume) {
    return null;
  }
  return (
    <>
      {failure && <Notice kind="error">{errorMessage(failure)}</Notice>}
      <div className="button-row">
        {viewer.can_download_resume && (
          <button type="button" disabled={download.isPending} onClick={() => download.mutate()}>
            {download.isPending ? "Preparing…" : "Download resume"}
          </button>
        )}
        {viewer.can_withdraw && (
          <button
            type="button"
            disabled={withdraw.isPending}
            onClick={() => {
              if (
                window.confirm(
                  "Withdraw this application? You cannot apply to this job again afterwards.",
                )
              ) {
                withdraw.mutate();
              }
            }}
          >
            {withdraw.isPending ? "Withdrawing…" : "Withdraw application"}
          </button>
        )}
      </div>
    </>
  );
}

export function ApplicationPage() {
  const { applicationId = "" } = useParams();
  const application = useApplication(applicationId);

  if (application.isPending) {
    return <Splash />;
  }
  if (application.isError) {
    const notFound = application.error instanceof ApiError && application.error.status === 404;
    return (
      <>
        <h1>{notFound ? "Application not found" : "Something went wrong"}</h1>
        <p className="muted">
          {notFound
            ? "This application does not exist or is not available to you."
            : errorMessage(application.error)}
        </p>
        {!notFound && (
          <button type="button" onClick={() => void application.refetch()}>
            Try again
          </button>
        )}
      </>
    );
  }

  const data = application.data;
  const { opportunity, applicant, viewer } = data;

  return (
    <>
      <div className="page-heading">
        <h1>
          {viewer.is_applicant ? "Your application" : `Application from ${applicant.display_name}`}
        </h1>
        <span className={statusBadgeClass(data.status)}>
          {APPLICATION_STATUS_LABELS[data.status]}
        </span>
      </div>
      <p>
        For <Link to={`/opportunities/${opportunity.id}`}>{opportunity.title}</Link>
        {opportunity.organization && <> at {opportunity.organization.name}</>}
      </p>
      {viewer.is_applicant && opportunity.status !== "PUBLISHED" && (
        <p className="muted">This job is no longer open to new applications.</p>
      )}
      {data.status === "WITHDRAWN" && !viewer.is_applicant && (
        <p className="muted">The applicant withdrew, so the resume is no longer available.</p>
      )}

      <section className="card" aria-labelledby="application-heading">
        <h2 id="application-heading">Application</h2>
        {!viewer.is_applicant && (
          <Link to={`/users/${applicant.id}`} className="person">
            <Avatar name={applicant.display_name} url={applicant.avatar_url} size={36} />
            <span>
              <strong>{applicant.display_name}</strong>
              {data.headline && <span className="muted"> · {data.headline}</span>}
            </span>
          </Link>
        )}
        <h3>Note to the employer</h3>
        {data.cover_note ? (
          <p className="prose">{data.cover_note}</p>
        ) : (
          <p className="muted">No note was included.</p>
        )}
        <Actions application={data} />
      </section>

      {viewer.can_manage && (
        <section className="card" aria-labelledby="decide-heading">
          <h2 id="decide-heading">Decide</h2>
          {viewer.next_statuses.length === 0 ? (
            <p className="muted">This application has been decided and cannot be moved again.</p>
          ) : (
            <StageControl
              applicationId={data.id}
              applicantName={applicant.display_name}
              status={data.status}
              nextStatuses={viewer.next_statuses}
              withNote
            />
          )}
          <p>
            <Link to={`/opportunities/${opportunity.id}/applications`}>
              All applications for this job
            </Link>
          </p>
        </section>
      )}

      <section className="card" aria-labelledby="history-heading">
        <h2 id="history-heading">History</h2>
        <ol className="entry-list">
          {data.history.map((step) => (
            <li key={`${step.to_status}-${step.created_at}`} className="entry">
              <span>
                {stepText(step)}
                {step.actor && step.from_status !== "" && step.to_status !== "WITHDRAWN" && (
                  <span className="muted"> by {step.actor.display_name}</span>
                )}
                {step.note && <span className="prose step-note">{step.note}</span>}
              </span>
              <time className="muted" dateTime={step.created_at}>
                {timeFormat.format(new Date(step.created_at))}
              </time>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
