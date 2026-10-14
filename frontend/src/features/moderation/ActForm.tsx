import { useId, useState, type FormEvent } from "react";

import { ACTION_LABELS, TIMED_ACTIONS, type ActionType } from "./api";

/** What a moderator chose to do, ready to send. `until` is an instant, or null. */
export interface Chosen {
  action: ActionType;
  reason: string;
  until: string | null;
}

// Questions for the actions that cut someone off or cannot be taken back.
const SURE: Partial<Record<ActionType, string>> = {
  REMOVE: "Remove this for good? This cannot be undone.",
  SUSPEND: "Suspend? They are signed out everywhere at once and cannot sign back in.",
};

/** The end of the chosen day, where the moderator is. */
function endOfDay(date: string): string {
  return new Date(`${date}T23:59:59`).toISOString();
}

function tomorrow(): string {
  const day = new Date(Date.now() + 24 * 60 * 60 * 1000);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${String(day.getFullYear())}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

/**
 * Choosing an action, a reason, and (for a suspension or a restriction) how long it lasts.
 * Only what the server says is possible is offered; the server decides again on submit.
 */
export function ActForm({
  actions,
  kind,
  busy,
  onAct,
}: {
  actions: ActionType[];
  /** What is being acted on, in words: "person", "opportunity". */
  kind: string;
  busy: boolean;
  onAct: (chosen: Chosen) => void;
}) {
  const id = useId();
  const [action, setAction] = useState<ActionType | "">("");
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const timed = action !== "" && TIMED_ACTIONS.includes(action);

  return (
    <form
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        if (!action || !reason.trim()) {
          return;
        }
        const question = SURE[action];
        if (question && !window.confirm(question)) {
          return;
        }
        onAct({ action, reason: reason.trim(), until: timed && until ? endOfDay(until) : null });
      }}
    >
      <div className="field">
        <label htmlFor={`${id}-action`}>What to do</label>
        <select
          id={`${id}-action`}
          value={action}
          onChange={(event) => setAction(event.target.value as ActionType | "")}
        >
          <option value="">Choose…</option>
          {actions.map((value) => (
            <option key={value} value={value}>
              {ACTION_LABELS[value]}
            </option>
          ))}
        </select>
      </div>
      {timed && (
        <div className="field">
          <label htmlFor={`${id}-until`}>Until (optional)</label>
          <input
            id={`${id}-until`}
            type="date"
            min={tomorrow()}
            aria-describedby={`${id}-until-hint`}
            value={until}
            onChange={(event) => setUntil(event.target.value)}
          />
          <p id={`${id}-until-hint`} className="field-hint">
            It ends by itself at the end of that day. Leave empty for until a moderator lifts it.
          </p>
        </div>
      )}
      <div className="field">
        <label htmlFor={`${id}-reason`}>Reason</label>
        <textarea
          id={`${id}-reason`}
          rows={3}
          maxLength={500}
          aria-describedby={`${id}-reason-hint`}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
        <p id={`${id}-reason-hint`} className="field-hint">
          {kind === "person"
            ? "The person is shown this."
            : `The people who run the ${kind} are shown this.`}{" "}
          Whoever reported it is never named to them.
        </p>
      </div>
      <button type="submit" className="primary" disabled={busy || !action || !reason.trim()}>
        Take action
      </button>
    </form>
  );
}
