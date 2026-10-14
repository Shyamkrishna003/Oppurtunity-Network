import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { ActForm } from "../features/moderation/ActForm";
import { ActionHistory } from "../features/moderation/ActionHistory";
import {
  CATEGORY_LABELS,
  REPORT_STATUS_LABELS,
  TARGET_LABELS,
  useDecideReport,
  useReport,
  type ReportDetail,
} from "../features/moderation/api";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function Decide({ report }: { report: ReportDetail }) {
  const decide = useDecideReport(report.id);
  const [note, setNote] = useState("");
  const kind = TARGET_LABELS[report.target.type].toLowerCase();
  const others = report.in_progress_on_target - 1;

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
        <>
          <h3>Act on the {kind}</h3>
          {others > 0 && (
            <p className="muted">
              This also settles the other {others} waiting about the same {kind}.
            </p>
          )}
          <ActForm
            actions={report.available_actions}
            kind={kind}
            busy={decide.isPending}
            onAct={(chosen) => decide.mutate({ kind: "resolve", ...chosen })}
          />
        </>
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
  const { target } = report;
  const kind = TARGET_LABELS[target.type].toLowerCase();
  const waiting = report.status === "OPEN" || report.status === "UNDER_REVIEW";
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
          <dt>{TARGET_LABELS[target.type]}</dt>
          <dd>
            <Link to={target.url}>{target.name}</Link>
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
        <ActionHistory actions={report.actions} />
        {/* Undoing something, or acting without a report, happens on the target's own page. */}
        <p>
          <Link to={`/moderation/targets/${target.type}/${target.id}`}>Moderate this {kind}</Link>
        </p>
      </section>
    </>
  );
}
