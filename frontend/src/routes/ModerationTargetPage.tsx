import { Link, useParams } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { ActForm } from "../features/moderation/ActForm";
import { ActionHistory } from "../features/moderation/ActionHistory";
import {
  TARGET_LABELS,
  useModerate,
  useModerationTarget,
  type TargetType,
} from "../features/moderation/api";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

/** A person, organization, community or opportunity as the moderators see it: how it
 *  stands, what has been done to it, and what can be done now. */
export function ModerationTargetPage() {
  const { targetType = "", targetId = "" } = useParams();
  const query = useModerationTarget(targetType, targetId);
  const moderate = useModerate();

  if (query.isPending) {
    return <Splash />;
  }
  if (query.isError) {
    const denied =
      query.error instanceof ApiError && (query.error.status === 403 || query.error.status === 404);
    return (
      <>
        <h1>{denied ? "Not available" : "Something went wrong"}</h1>
        <p className="muted">
          {denied ? "This does not exist, or this page is not for you." : errorMessage(query.error)}
        </p>
      </>
    );
  }

  const { target, standing, possible_actions: possible, actions } = query.data;
  const kind = TARGET_LABELS[target.type].toLowerCase();
  return (
    <>
      <p>
        <Link to="/moderation">All reports</Link>
      </p>
      <h1>Moderate {kind}</h1>
      <p>
        <Link to={target.url}>{target.name}</Link>
      </p>
      {standing.length > 0 ? (
        <ul className="chips" aria-label="How it stands">
          {standing.map((note) => (
            <li key={note} className={note === "Verified" ? "badge badge-ok" : "badge badge-error"}>
              {note}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">Nothing is in force against this {kind}.</p>
      )}

      <section className="card" aria-labelledby="act-heading">
        <h2 id="act-heading">Act</h2>
        {moderate.error && <Notice kind="error">{errorMessage(moderate.error)}</Notice>}
        {moderate.isSuccess && <Notice kind="ok">Done. It is recorded below.</Notice>}
        {possible.length > 0 ? (
          <ActForm
            // Start afresh once an action has gone through: what is possible has changed.
            key={actions[0]?.id ?? "none"}
            actions={possible}
            kind={kind}
            busy={moderate.isPending}
            onAct={(chosen) =>
              moderate.mutate({
                target_type: target.type as TargetType,
                target_id: target.id,
                ...chosen,
              })
            }
          />
        ) : (
          <p className="muted">There is nothing you can do to this {kind} from here.</p>
        )}
      </section>

      <section className="card" aria-labelledby="history-heading">
        <h2 id="history-heading">What moderators have done</h2>
        <ActionHistory actions={actions} />
      </section>
    </>
  );
}
