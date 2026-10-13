import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import {
  ACTION_DONE_LABELS,
  ACTION_LABELS,
  CATEGORY_LABELS,
  REPORT_STATUS_LABELS,
  TARGET_LABELS,
  useDecideReport,
  useModerate,
  useReport,
  type ActionType,
  type ReportDetail,
} from "../features/moderation/api";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function Decide({ report }: { report: ReportDetail }) {
  const decide = useDecideReport(report.id);
  const [action, setAction] = useState<ActionType | "">("");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const kind = TARGET_LABELS[report.target.type].toLowerCase();

  return (
    <section className="card" aria-labelledby="decide-heading">
      <h2 id="decide-heading">Decide</h2>
      {decide.error && <Notice kind="error">{errorMessage(decide.error)}</Notice>}
      {report.status === "OPEN" && (
        <p>
          <button
            type="button"
            disabled={decide.isPending}
            onClick={() => decide.mutate({ kind: "claim" })}
          >
            Take this report
          </button>
        </p>
      )}

      {report.available_actions.length > 0 ? (
        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            const sure =
              action === "REMOVE"
                ? `Remove this ${kind} for good? This cannot be undone.`
                : `Hide this ${kind}? Its owners are told, with your reason.`;
            if (action && reason.trim() && window.confirm(sure)) {
              decide.mutate({ kind: "resolve", action, reason: reason.trim() });
            }
          }}
        >
          <h3>Act on the {kind}</h3>
          <div className="field">
            <label htmlFor="act-action">What to do</label>
            <select
              id="act-action"
              value={action}
              onChange={(event) => setAction(event.target.value as ActionType | "")}
            >
              <option value="">Choose…</option>
              {report.available_actions.map((value) => (
                <option key={value} value={value}>
                  {ACTION_LABELS[value]}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="act-reason">Reason</label>
            <textarea
              id="act-reason"
              rows={3}
              maxLength={500}
              aria-describedby="act-reason-hint"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            <p id="act-reason-hint" className="field-hint">
              The owners of the {kind} see this. Whoever reported it is not named to them.
              {report.in_progress_on_target > 1 &&
                ` This also settles the other ${String(report.in_progress_on_target - 1)} waiting about the same ${kind}.`}
            </p>
          </div>
          <button
            type="submit"
            className="primary"
            disabled={decide.isPending || !action || !reason.trim()}
          >
            Take action
          </button>
        </form>
      ) : (
        <p className="muted">Nothing can be done to this {kind} from here; you can dismiss.</p>
      )}

      <form
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          decide.mutate({ kind: "dismiss", note: note.trim() });
        }}
      >
        <h3>Or dismiss it</h3>
        <div className="field">
          <label htmlFor="dismiss-note">Note for other moderators (optional)</label>
          <input
            id="dismiss-note"
            maxLength={500}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </div>
        <button type="submit" disabled={decide.isPending}>
          No action needed
        </button>
      </form>
    </section>
  );
}

/** Puts back an opportunity that was hidden, with a reason its owners see. */
function Restore({ report }: { report: ReportDetail }) {
  const moderate = useModerate();
  const [reason, setReason] = useState("");
  return (
    <form
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        moderate.mutate({
          target_type: report.target.type,
          target_id: report.target.id,
          action: "RESTORE",
          reason: reason.trim(),
        });
      }}
    >
      {moderate.error && <Notice kind="error">{errorMessage(moderate.error)}</Notice>}
      <div className="search-form">
        <input
          aria-label="Reason for restoring"
          placeholder="Why it can be shown again"
          maxLength={500}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
        <button type="submit" disabled={moderate.isPending || !reason.trim()}>
          Restore
        </button>
      </div>
    </form>
  );
}

export function ModerationReportPage() {
  const { reportId = "" } = useParams();
  const query = useReport(reportId);

  if (query.isPending) {
    return <Splash />;
  }
  if (query.isError) {
    const denied =
      query.error instanceof ApiError && (query.error.status === 403 || query.error.status === 404);
    return (
      <>
        <h1>{denied ? "Report not available" : "Something went wrong"}</h1>
        <p className="muted">
          {denied
            ? "This report does not exist, or this page is not for you."
            : errorMessage(query.error)}
        </p>
      </>
    );
  }

  const report = query.data;
  const waiting = report.status === "OPEN" || report.status === "UNDER_REVIEW";
  // Only something hidden can be put back; the newest action says how it stands.
  const hidden = report.target.type === "OPPORTUNITY" && report.actions[0]?.action_type === "HIDE";
  return (
    <>
      <p>
        <Link to="/moderation">All reports</Link>
      </p>
      <div className="page-heading">
        <h1>Report</h1>
        <span className={waiting ? "badge badge-error" : "badge"}>
          {REPORT_STATUS_LABELS[report.status]}
        </span>
      </div>

      <section className="card" aria-labelledby="about-heading">
        <h2 id="about-heading">What was reported</h2>
        <dl className="facts">
          <dt>{TARGET_LABELS[report.target.type]}</dt>
          <dd>
            <Link to={report.target.url}>{report.target.name}</Link>
          </dd>
          <dt>Problem</dt>
          <dd>{CATEGORY_LABELS[report.category]}</dd>
          <dt>Reported by</dt>
          <dd>
            <Link to={`/users/${report.reporter.id}`}>{report.reporter.display_name}</Link>,{" "}
            {timeFormat.format(new Date(report.created_at))}
          </dd>
          {report.assigned_to && (
            <>
              <dt>With</dt>
              <dd>{report.assigned_to.display_name}</dd>
            </>
          )}
          {report.resolution_note && (
            <>
              <dt>Note</dt>
              <dd>{report.resolution_note}</dd>
            </>
          )}
        </dl>
        {report.description ? (
          <p className="prose">{report.description}</p>
        ) : (
          <p className="muted">The reporter added no details.</p>
        )}
      </section>

      {waiting && <Decide report={report} />}

      <section className="card" aria-labelledby="history-heading">
        <h2 id="history-heading">What moderators have done to it</h2>
        {report.actions.length === 0 ? (
          <p className="muted">Nothing yet.</p>
        ) : (
          <ol className="entry-list">
            {report.actions.map((action) => (
              <li key={action.id} className="entry">
                <span>
                  <strong>{ACTION_DONE_LABELS[action.action_type]}</strong> by{" "}
                  {action.actor.display_name}
                  <span className="muted step-note">{action.reason}</span>
                </span>
                <time className="muted" dateTime={action.created_at}>
                  {timeFormat.format(new Date(action.created_at))}
                </time>
              </li>
            ))}
          </ol>
        )}
        {hidden && <Restore report={report} />}
      </section>
    </>
  );
}
