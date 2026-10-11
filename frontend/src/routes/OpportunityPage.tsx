import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import {
  useArchiveOpportunity,
  useCloseOpportunity,
  useDeleteOpportunity,
  useOpportunity,
  usePublishOpportunity,
} from "../features/opportunities/api";
import { formatDate, formatSalary } from "../features/opportunities/format";
import {
  CLOSE_REASON_LABELS,
  EMPLOYMENT_TYPE_LABELS,
  STATUS_LABELS,
  VISIBILITY_LABELS,
  type CloseReason,
  type OpportunityDetail,
} from "../features/opportunities/types";
import { EXPERIENCE_LEVELS, formatLocation, WORK_MODES } from "../features/profile/labels";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

/** What each missing-field key from the server means in the form's own words. */
const FIELD_LABELS: Record<string, string> = {
  description: "Description",
  work_mode: "Work mode",
  country_code: "Country code",
  city: "City",
  deadline: "Apply-by date",
  skill_ids: "Skills needed",
  "job.employment_type": "Employment type",
  "job.experience_level": "Experience level",
  "job.salary_currency": "Salary currency",
  "job.salary_period": "Salary period",
};

function ManagerPanel({ opportunity }: { opportunity: OpportunityDetail }) {
  const navigate = useNavigate();
  const publish = usePublishOpportunity(opportunity.id);
  const close = useCloseOpportunity(opportunity.id);
  const archive = useArchiveOpportunity(opportunity.id);
  const remove = useDeleteOpportunity(opportunity.id);
  const [reason, setReason] = useState<CloseReason>("FILLED");
  const busy = publish.isPending || close.isPending || archive.isPending || remove.isPending;
  const { status } = opportunity;
  const editable = opportunity.viewer.editable_fields;
  const canEdit = editable === null || editable.length > 0;

  const failure = publish.error ?? close.error ?? archive.error ?? remove.error;
  const missing =
    publish.error instanceof ApiError && publish.error.code === "incomplete"
      ? Object.entries(publish.error.fieldErrors)
      : [];

  return (
    <section className="card" aria-labelledby="manage-heading">
      <h2 id="manage-heading">Manage</h2>
      {missing.length > 0 ? (
        <Notice kind="error">
          <p>Complete these details before publishing:</p>
          <ul>
            {missing.map(([field, messages]) => (
              <li key={field}>
                <strong>{FIELD_LABELS[field] ?? field}:</strong> {messages.join(" ")}
              </li>
            ))}
          </ul>
        </Notice>
      ) : (
        failure && <Notice kind="error">{errorMessage(failure)}</Notice>
      )}

      {status === "DRAFT" && (
        <p className="muted">This is a draft. Only you and the people who manage it can see it.</p>
      )}
      {opportunity.moderation_status !== "VISIBLE" && (
        <Notice kind="error">
          A moderator has hidden this opportunity. Other people cannot see it.
        </Notice>
      )}
      {status === "PUBLISHED" && opportunity.visibility === "COMMUNITY" && (
        <p className="muted">
          This job is limited to communities. It becomes visible to a community&apos;s members once
          it has been shared there and approved.
        </p>
      )}

      <div className="button-row">
        {canEdit && (
          <Link to={`/opportunities/${opportunity.id}/edit`} className="button">
            Edit
          </Link>
        )}
        {status === "DRAFT" && (
          <>
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => publish.mutate()}
            >
              {publish.isPending ? "Publishing…" : "Publish"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (window.confirm("Delete this draft? This cannot be undone.")) {
                  remove.mutate(undefined, {
                    onSuccess: () => void navigate("/my/opportunities"),
                  });
                }
              }}
            >
              Delete draft
            </button>
          </>
        )}
        {(status === "CLOSED" || status === "EXPIRED") && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              if (window.confirm("Archive this job? It will disappear from every public page.")) {
                archive.mutate();
              }
            }}
          >
            Archive
          </button>
        )}
      </div>

      {status === "PUBLISHED" && (
        <form
          className="search-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (window.confirm("Close this job? It stays visible, marked as closed.")) {
              close.mutate(reason);
            }
          }}
        >
          <select
            aria-label="Reason for closing"
            value={reason}
            onChange={(event) => setReason(event.target.value as CloseReason)}
          >
            {Object.entries(CLOSE_REASON_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <button type="submit" disabled={busy}>
            {close.isPending ? "Closing…" : "Close job"}
          </button>
        </form>
      )}
    </section>
  );
}

export function OpportunityPage() {
  const { opportunityId = "" } = useParams();
  const opportunity = useOpportunity(opportunityId);

  if (opportunity.isPending) {
    return <Splash />;
  }
  if (opportunity.isError) {
    const notFound = opportunity.error instanceof ApiError && opportunity.error.status === 404;
    return (
      <>
        <h1>{notFound ? "Opportunity not found" : "Something went wrong"}</h1>
        <p className="muted">
          {notFound
            ? "This opportunity does not exist, has been removed, or is not available to you."
            : errorMessage(opportunity.error)}
        </p>
        {!notFound && (
          <button type="button" onClick={() => void opportunity.refetch()}>
            Try again
          </button>
        )}
      </>
    );
  }

  const data = opportunity.data;
  const { job } = data;
  const location = formatLocation(data);
  const salary = formatSalary(job);
  const facts = [
    job.employment_type && EMPLOYMENT_TYPE_LABELS[job.employment_type],
    job.experience_level && EXPERIENCE_LEVELS[job.experience_level],
    data.work_mode && WORK_MODES[data.work_mode],
    location,
  ].filter(Boolean);
  const open = data.status === "PUBLISHED";

  return (
    <>
      <div className="page-heading">
        <h1>{data.title}</h1>
        <span className={open ? "badge badge-ok" : "badge"}>{STATUS_LABELS[data.status]}</span>
      </div>
      <p>
        {data.organization ? (
          <>
            <Link to={`/organizations/${data.organization.id}`}>{data.organization.name}</Link>
            {data.organization.verification_status === "VERIFIED" && (
              <span className="badge badge-ok"> Verified</span>
            )}
          </>
        ) : (
          data.posted_by && <>Posted by {data.posted_by.display_name}</>
        )}
      </p>
      {facts.length > 0 && <p className="muted">{facts.join(" · ")}</p>}

      {data.status === "CLOSED" && (
        <Notice kind="error">This job is closed and no longer takes applications.</Notice>
      )}
      {data.status === "EXPIRED" && (
        <Notice kind="error">The deadline for this job has passed.</Notice>
      )}

      {data.viewer.can_manage && <ManagerPanel opportunity={data} />}

      <section className="card" aria-labelledby="about-heading">
        <h2 id="about-heading">About the job</h2>
        {data.description ? (
          <p className="prose">{data.description}</p>
        ) : (
          <p className="muted">No description yet.</p>
        )}
        <dl className="facts">
          {salary && (
            <>
              <dt>Salary</dt>
              <dd>{salary}</dd>
            </>
          )}
          {job.department && (
            <>
              <dt>Department</dt>
              <dd>{job.department}</dd>
            </>
          )}
          <dt>Openings</dt>
          <dd>{job.openings}</dd>
          {data.deadline && (
            <>
              <dt>Apply by</dt>
              <dd>{formatDate(data.deadline)}</dd>
            </>
          )}
          {data.published_at && (
            <>
              <dt>Published</dt>
              <dd>{formatDate(data.published_at)}</dd>
            </>
          )}
          {data.viewer.can_manage && (
            <>
              <dt>Visible to</dt>
              <dd>{VISIBILITY_LABELS[data.visibility]}</dd>
            </>
          )}
        </dl>
      </section>

      <section className="card" aria-labelledby="skills-heading">
        <h2 id="skills-heading">Skills</h2>
        {data.skills.length === 0 ? (
          <p className="muted">No skills listed yet.</p>
        ) : (
          <ul className="chips">
            {data.skills.map((skill) => (
              <li key={skill.id} className="chip">
                {skill.name}
              </li>
            ))}
          </ul>
        )}
      </section>

      {open && job.application_method === "EXTERNAL" && (
        <section className="card" aria-labelledby="apply-heading">
          <h2 id="apply-heading">How to apply</h2>
          <p>
            Applications for this job are taken on another website:{" "}
            {/* User-supplied link: no referrer, and no access to this window. */}
            <a href={job.external_url} target="_blank" rel="noopener noreferrer nofollow">
              {job.external_url}
            </a>
          </p>
        </section>
      )}
    </>
  );
}
