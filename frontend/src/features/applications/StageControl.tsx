import { useId, useState } from "react";

import { TextAreaField } from "../../components/Field";
import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { ApiError } from "../../services/http";
import { useTransition } from "./api";
import { APPLICATION_STATUS_LABELS, NOTE_MAX, type ApplicationStatus } from "./types";

interface Props {
  applicationId: string;
  /** Named in the confirmation and in labels, so each control says whose application it is. */
  applicantName: string;
  status: ApplicationStatus;
  /** From the server: where this viewer may move it. Nothing is rendered when empty. */
  nextStatuses: ApplicationStatus[];
  /** Offer a private note with the move (the application page; not the compact rows). */
  withNote?: boolean;
}

function optionLabel(status: ApplicationStatus): string {
  return status === "REJECTED" ? "Reject" : APPLICATION_STATUS_LABELS[status];
}

export function StageControl({
  applicationId,
  applicantName,
  status,
  nextStatuses,
  withNote = false,
}: Props) {
  const move = useTransition(applicationId);
  const selectId = useId();
  const [target, setTarget] = useState<ApplicationStatus | "">("");
  const [note, setNote] = useState("");

  if (nextStatuses.length === 0) {
    return null;
  }
  // The list changes after a move, and the earlier choice may no longer be on it.
  const chosen = target !== "" && nextStatuses.includes(target) ? target : "";
  const stale = move.error instanceof ApiError && move.error.code === "stale_state";

  function submit() {
    if (chosen === "") {
      return;
    }
    const final = chosen === "REJECTED" || chosen === "HIRED";
    const question =
      chosen === "REJECTED"
        ? `Reject ${applicantName}'s application? This cannot be undone.`
        : `Mark ${applicantName} as hired? This cannot be undone.`;
    if (final && !window.confirm(question)) {
      return;
    }
    move.mutate(
      { to: chosen, from: status, note: note.trim() },
      {
        onSuccess: () => {
          setTarget("");
          setNote("");
        },
      },
    );
  }

  return (
    <form
      className={withNote ? undefined : "search-form"}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {move.isError && (
        <Notice kind="error">
          {stale
            ? "Someone else updated this application in the meantime. It now shows where it stands; choose again if you still want to move it."
            : errorMessage(move.error)}
        </Notice>
      )}
      <div className={withNote ? "field" : undefined}>
        <label htmlFor={selectId} className={withNote ? undefined : "visually-hidden"}>
          Move {withNote ? "to" : `${applicantName} to`}
        </label>
        <select
          id={selectId}
          value={chosen}
          onChange={(event) => {
            setTarget(event.target.value as ApplicationStatus | "");
            move.reset();
          }}
        >
          <option value="">Move to…</option>
          {nextStatuses.map((next) => (
            <option key={next} value={next}>
              {optionLabel(next)}
            </option>
          ))}
        </select>
      </div>
      {withNote && (
        <TextAreaField
          label="Note for your team (optional)"
          hint="Only the people who manage this job can read it. The applicant never sees it."
          rows={3}
          maxLength={NOTE_MAX}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      )}
      <button type="submit" disabled={chosen === "" || move.isPending}>
        {move.isPending ? "Saving…" : "Update"}
        {!withNote && (
          <>
            {" "}
            <span className="visually-hidden">{applicantName}</span>
          </>
        )}
      </button>
    </form>
  );
}
