import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { useAnswerConnection, useRemoveConnection, useRequestConnection } from "./api";
import type { ConnectionRef } from "./types";

interface Props {
  userId: string;
  name: string;
  /** Null when there is neither a connection nor a request between the two. */
  connection: ConnectionRef | null;
}

/**
 * What the viewer can do about their connection with one person: ask, take the request
 * back, answer theirs, or end the connection. Used on a profile and in the lists.
 */
export function ConnectionActions({ userId, name, connection }: Props) {
  const request = useRequestConnection();
  const answer = useAnswerConnection();
  const remove = useRemoveConnection();
  const busy = request.isPending || answer.isPending || remove.isPending;
  const failure = request.error ?? answer.error ?? remove.error;
  const target = connection && { connectionId: connection.id, userId };

  return (
    <>
      <div className="button-row">
        {!target && (
          <button
            type="button"
            className="primary"
            disabled={busy}
            onClick={() => request.mutate(userId)}
          >
            Connect <span className="visually-hidden">with {name}</span>
          </button>
        )}
        {target && connection.state === "INCOMING" && (
          <>
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => answer.mutate({ ...target, accept: true })}
            >
              Accept <span className="visually-hidden">{name}</span>
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => answer.mutate({ ...target, accept: false })}
            >
              Decline <span className="visually-hidden">{name}</span>
            </button>
          </>
        )}
        {target && connection.state === "OUTGOING" && (
          <button type="button" disabled={busy} onClick={() => remove.mutate(target)}>
            Cancel request <span className="visually-hidden">to {name}</span>
          </button>
        )}
        {target && connection.state === "CONNECTED" && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              if (window.confirm(`Remove ${name} from your connections?`)) {
                remove.mutate(target);
              }
            }}
          >
            Remove <span className="visually-hidden">{name}</span>
          </button>
        )}
      </div>
      {failure && <Notice kind="error">{errorMessage(failure)}</Notice>}
    </>
  );
}
