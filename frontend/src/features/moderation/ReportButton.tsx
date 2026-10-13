import { useId, useState, type FormEvent } from "react";

import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { ApiError } from "../../services/http";
import { useMe, useSessionStatus } from "../auth/api";
import { CATEGORY_LABELS, useFileReport, type ReportCategory, type TargetType } from "./api";

const MAX_DESCRIPTION = 2000;

/**
 * Lets a signed-in person report something to the moderators. Renders nothing for
 * visitors, and nothing where the server would refuse anyway (pass `own` for the viewer's
 * own content).
 */
export function ReportButton({
  targetType,
  targetId,
  what,
  own = false,
}: {
  targetType: TargetType;
  targetId: string;
  /** What is being reported, in the sentence "Report this …". */
  what: string;
  own?: boolean;
}) {
  const session = useSessionStatus();
  const me = useMe();
  const report = useFileReport();
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState<ReportCategory | "">("");
  const [description, setDescription] = useState("");
  const id = useId();

  if (session !== "authenticated" || own) {
    return null;
  }
  if (report.isSuccess) {
    return (
      <Notice kind="ok">
        Thank you. A moderator will look at it, and you will be told when they have.
      </Notice>
    );
  }
  if (!open) {
    return (
      <p className="report-line">
        <button type="button" className="link" onClick={() => setOpen(true)}>
          Report this {what}
        </button>
      </p>
    );
  }

  const already = report.error instanceof ApiError && report.error.code === "already_reported";
  return (
    <section className="card" aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`}>Report this {what}</h2>
      <p className="muted">
        Reports go to the platform&apos;s moderators. Whoever you report is not told it was you.
      </p>
      {me.data && !me.data.email_verified && (
        <Notice kind="error">Confirm your email address before reporting.</Notice>
      )}
      {report.error && (
        <Notice kind="error">
          {already
            ? "You have already reported this, and it is still being looked at."
            : errorMessage(report.error)}
        </Notice>
      )}
      <form
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          if (category) {
            report.mutate({
              target_type: targetType,
              target_id: targetId,
              category,
              description: description.trim(),
            });
          }
        }}
      >
        <div className="field">
          <label htmlFor={`${id}-category`}>What is wrong with it?</label>
          <select
            id={`${id}-category`}
            required
            value={category}
            onChange={(event) => setCategory(event.target.value as ReportCategory | "")}
          >
            <option value="">Choose…</option>
            {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor={`${id}-description`}>Anything that helps us understand (optional)</label>
          <textarea
            id={`${id}-description`}
            rows={4}
            maxLength={MAX_DESCRIPTION}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
        <div className="button-row">
          <button type="submit" className="primary" disabled={!category || report.isPending}>
            {report.isPending ? "Sending…" : "Send report"}
          </button>
          <button
            type="button"
            disabled={report.isPending}
            onClick={() => {
              setOpen(false);
              report.reset();
            }}
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}
