import { useId, useState } from "react";
import { Link } from "react-router";

import { Confetti } from "../../components/Confetti";
import { TextAreaField } from "../../components/Field";
import { Notice } from "../../components/Notice";
import { ApiError } from "../../services/http";
import { useMe, useSessionStatus } from "../auth/api";
import type { OpportunityDetail } from "../opportunities/types";
import { useApply } from "./api";
import {
  APPLICATION_STATUS_LABELS,
  COVER_NOTE_MAX,
  RESUME_MAX_BYTES,
  statusBadgeClass,
} from "./types";

/** A quick check before uploading. The server decides for real, from the file's content. */
function resumeProblem(file: File | null): string | null {
  if (!file) {
    return "Attach your resume as a PDF.";
  }
  if (file.size > RESUME_MAX_BYTES) {
    return "The resume must be 5 MB or smaller.";
  }
  if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
    return "The resume must be a PDF file.";
  }
  return null;
}

function ApplyForm({ opportunityId, onApplied }: { opportunityId: string; onApplied: () => void }) {
  const apply = useApply(opportunityId);
  const fileId = useId();
  const [resume, setResume] = useState<File | null>(null);
  const [coverNote, setCoverNote] = useState("");
  const [fileError, setFileError] = useState<string | null>(null);

  const serverErrors = apply.error instanceof ApiError ? apply.error.fieldErrors : {};
  const resumeError = fileError ?? serverErrors.resume?.join(" ");
  // Shown above the form unless it is about a field, where it appears instead.
  const formError =
    apply.error && !serverErrors.resume && !serverErrors.cover_note
      ? apply.error instanceof ApiError
        ? apply.error.message
        : "Something went wrong. Try again."
      : null;

  function submit() {
    const problem = resumeProblem(resume);
    setFileError(problem);
    if (!problem && resume) {
      apply.mutate({ resume, coverNote: coverNote.trim() }, { onSuccess: onApplied });
    }
  }

  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {formError && <Notice kind="error">{formError}</Notice>}
      <div className="field">
        <label htmlFor={fileId}>Resume (PDF)</label>
        <input
          id={fileId}
          type="file"
          accept="application/pdf,.pdf"
          aria-describedby={`${fileId}-hint${resumeError ? ` ${fileId}-error` : ""}`}
          aria-invalid={Boolean(resumeError)}
          onChange={(event) => {
            const file = event.target.files?.[0] ?? null;
            setResume(file);
            setFileError(file ? resumeProblem(file) : null);
            apply.reset();
          }}
        />
        <p id={`${fileId}-hint`} className="field-hint">
          5 MB at most. Only the people who manage this job can open it.
        </p>
        {resumeError && (
          <p id={`${fileId}-error`} className="field-error" role="alert">
            {resumeError}
          </p>
        )}
      </div>
      <TextAreaField
        label="Note to the employer (optional)"
        rows={5}
        maxLength={COVER_NOTE_MAX}
        value={coverNote}
        onChange={(event) => setCoverNote(event.target.value)}
        error={serverErrors.cover_note?.join(" ")}
      />
      <button type="submit" className="primary" disabled={apply.isPending}>
        {apply.isPending ? "Sending…" : "Send application"}
      </button>
    </form>
  );
}

/** The "Apply" section of a job page, in whichever form fits the viewer. Renders nothing
 *  when there is nothing to offer them (their own job, a closed one they never applied to). */
export function ApplyPanel({ opportunity }: { opportunity: OpportunityDetail }) {
  const session = useSessionStatus();
  const me = useMe();
  // True only for an application sent from this page just now, not one found on arrival.
  const [justApplied, setJustApplied] = useState(false);
  const { application, can_apply: canApply } = opportunity.viewer;
  const takesApplicationsHere =
    opportunity.status === "PUBLISHED" && opportunity.job?.application_method === "INTERNAL";

  let content;
  if (application) {
    content = (
      <>
        {justApplied && <Confetti />}
        <p>
          <span className={statusBadgeClass(application.status)}>
            {APPLICATION_STATUS_LABELS[application.status]}
          </span>{" "}
          You have applied to this job.
        </p>
        <Link to={`/applications/${application.id}`} className="button">
          View your application
        </Link>
      </>
    );
  } else if (session === "anonymous" && takesApplicationsHere) {
    content = (
      <>
        <p>Sign in to apply to this job with your resume.</p>
        <Link
          to={`/login?next=${encodeURIComponent(`/opportunities/${opportunity.id}`)}`}
          className="button primary"
        >
          Sign in to apply
        </Link>
      </>
    );
  } else if (canApply && me.data && !me.data.email_verified) {
    content = (
      <Notice kind="error">
        Confirm your email address before applying. Use the link we sent you, or ask for a new one
        at the top of this page.
      </Notice>
    );
  } else if (canApply) {
    content = <ApplyForm opportunityId={opportunity.id} onApplied={() => setJustApplied(true)} />;
  } else {
    return null;
  }

  return (
    <section className="card" aria-labelledby="application-heading">
      <h2 id="application-heading">{application ? "Your application" : "Apply"}</h2>
      {content}
    </section>
  );
}
