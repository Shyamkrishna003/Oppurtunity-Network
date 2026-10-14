import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import {
  CATEGORY_LABELS,
  REPORT_STATUS_LABELS,
  useCommunityReport,
  useDecideCommunityReport,
  type CommunityReportDetail,
} from "../features/moderation/api";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function Decide({ communityId, report }: { communityId: string; report: CommunityReportDetail }) {
  const decide = useDecideCommunityReport(communityId, report.id);
  const navigate = useNavigate();
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const others = report.in_progress_on_target - 1;

  if (!report.can_decide) {
    return (
      <section className="card" aria-labelledby="decide-heading">
        <h2 id="decide-heading">Decide</h2>
        <p className="muted">
          This one is not yours to decide: it is about something you manage, or you reported it.
          Another moderator of the community will.
        </p>
      </section>
    );
  }
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

      {report.shown_in_community ? (
        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (
              reason.trim() &&
              window.confirm("Remove it from this community? Whoever shared it is told.")
            ) {
              decide.mutate({ kind: "remove", reason: reason.trim() });
            }
          }}
        >
          <h3>Remove it from this community</h3>
          <p className="muted">
            It stays wherever else it is shown.
            {others > 0 && ` This also settles the other ${String(others)} waiting about it here.`}
          </p>
          <div className="field">
            <label htmlFor="remove-reason">Reason</label>
            <textarea
              id="remove-reason"
              rows={3}
              maxLength={500}
              aria-describedby="remove-reason-hint"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            <p id="remove-reason-hint" className="field-hint">
              For the community&apos;s other moderators and its record.
            </p>
          </div>
          <button type="submit" className="primary" disabled={decide.isPending || !reason.trim()}>
            Remove from this community
          </button>
        </form>
      ) : (
        <p className="muted">
          This community no longer shows it, so there is nothing to remove. You can dismiss.
        </p>
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

      <h3>Or pass it on</h3>
      <p className="muted">
        For something that should not be on the platform at all. The platform&apos;s moderators take
        it from here, and it leaves this list.
      </p>
      <button
        type="button"
        disabled={decide.isPending}
        onClick={() => {
          if (window.confirm("Pass this report to the platform's moderators?")) {
            decide.mutate(
              { kind: "escalate" },
              { onSuccess: () => void navigate(`/communities/${communityId}/reports`) },
            );
          }
        }}
      >
        Pass to the platform&apos;s moderators
      </button>
    </section>
  );
}

export function CommunityReportPage() {
  const { communityId = "", reportId = "" } = useParams();
  const query = useCommunityReport(communityId, reportId);

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
  return (
    <>
      <p>
        <Link to={`/communities/${communityId}/reports`}>All of the community&apos;s reports</Link>
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
          <dt>Opportunity</dt>
          <dd>
            <Link to={report.target.url}>{report.target.name}</Link>
          </dd>
          <dt>Problem</dt>
          <dd>{CATEGORY_LABELS[report.category]}</dd>
          <dt>Reported</dt>
          <dd>{timeFormat.format(new Date(report.created_at))}, by a member</dd>
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

      {waiting && <Decide communityId={communityId} report={report} />}
    </>
  );
}
