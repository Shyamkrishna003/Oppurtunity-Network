import { formatDate } from "../opportunities/format";
import { ACTION_DONE_LABELS, type ModerationAction } from "./api";

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

/** What moderators have done to something, newest first. */
export function ActionHistory({ actions }: { actions: ModerationAction[] }) {
  if (actions.length === 0) {
    return <p className="muted">Nothing yet.</p>;
  }
  return (
    <ol className="entry-list">
      {actions.map((action) => (
        <li key={action.id} className="entry">
          <span>
            <strong>{ACTION_DONE_LABELS[action.action_type]}</strong> by {action.actor.display_name}
            {action.expires_at && <>, until {formatDate(action.expires_at)}</>}
            <span className="muted step-note">{action.reason}</span>
          </span>
          <time className="muted" dateTime={action.created_at}>
            {timeFormat.format(new Date(action.created_at))}
          </time>
        </li>
      ))}
    </ol>
  );
}
