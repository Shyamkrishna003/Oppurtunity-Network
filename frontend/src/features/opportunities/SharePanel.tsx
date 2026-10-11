import { useState } from "react";
import { Link } from "react-router";

import { CheckboxField } from "../../components/Field";
import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { ApiError } from "../../services/http";
import { useShareOptions, useShares, useShareWith, useWithdrawShare } from "./api";
import { SHARE_STATUS_LABELS, type OpportunityDetail, type ShareOption } from "./types";

function optionHint(option: ShareOption): string {
  if (option.outcome === null) {
    return "This community does not let you share opportunities.";
  }
  const again = option.current === "REJECTED" ? "Offer it again: " : "";
  return option.outcome === "APPROVED"
    ? `${again}it will be shown to members straight away.`
    : `${again}a moderator of the community reviews it first.`;
}

/** Share a published opportunity with communities, and follow each one's decision. */
export function SharePanel({ opportunity }: { opportunity: OpportunityDetail }) {
  const shares = useShares(opportunity.id, true);
  const options = useShareOptions(opportunity.id, true);
  const share = useShareWith(opportunity.id);
  const withdraw = useWithdrawShare(opportunity.id);
  const [chosen, setChosen] = useState<string[]>([]);

  // Communities that can still be offered this opportunity: not there yet, or rejected.
  const available = (options.data ?? []).filter(
    (option) => option.current === null || option.current === "REJECTED",
  );
  const names = new Map((options.data ?? []).map((o) => [o.community.id, o.community.name]));
  const refused =
    share.error instanceof ApiError && share.error.code === "cannot_share"
      ? Object.entries(share.error.fieldErrors)
      : [];

  function toggle(communityId: string, on: boolean) {
    setChosen(on ? [...chosen, communityId] : chosen.filter((id) => id !== communityId));
  }

  return (
    <section className="card" aria-labelledby="share-heading">
      <h2 id="share-heading">Share with communities</h2>

      {shares.isError && <Notice kind="error">{errorMessage(shares.error)}</Notice>}
      {withdraw.isError && <Notice kind="error">{errorMessage(withdraw.error)}</Notice>}
      {shares.data && shares.data.length > 0 && (
        <ul className="entry-list" aria-label="Communities this is shared with">
          {shares.data.map((item) => (
            <li key={item.id} className="entry">
              <div>
                <Link to={`/communities/${item.community.id}`}>{item.community.name}</Link>{" "}
                <span className={item.status === "APPROVED" ? "badge badge-ok" : "badge"}>
                  {SHARE_STATUS_LABELS[item.status]}
                </span>
                {item.is_featured && <span className="badge badge-ok"> Featured</span>}
                {item.rejection_reason && (
                  <div className="muted">Reason: {item.rejection_reason}</div>
                )}
              </div>
              {item.status !== "REMOVED" && (
                <button
                  type="button"
                  disabled={withdraw.isPending}
                  onClick={() => withdraw.mutate(item.community.id)}
                >
                  Withdraw <span className="visually-hidden">from {item.community.name}</span>
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {options.isPending && (
        <p className="muted" role="status">
          Loading your communities…
        </p>
      )}
      {options.isError && <Notice kind="error">{errorMessage(options.error)}</Notice>}
      {options.isSuccess && options.data.length === 0 && (
        <p className="muted">
          You can share with communities you are a member of.{" "}
          <Link to="/communities">Find communities</Link>
        </p>
      )}
      {options.isSuccess && options.data.length > 0 && available.length === 0 && (
        <p className="muted">This is already shared with all of your communities.</p>
      )}

      {available.length > 0 && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            share.mutate(chosen, { onSuccess: () => setChosen([]) });
          }}
        >
          {refused.length > 0 ? (
            <Notice kind="error">
              <p>Nothing was shared, because:</p>
              <ul>
                {refused.map(([communityId, messages]) => (
                  <li key={communityId}>
                    <strong>{names.get(communityId) ?? "A community"}:</strong> {messages.join(" ")}
                  </li>
                ))}
              </ul>
            </Notice>
          ) : (
            share.isError && <Notice kind="error">{errorMessage(share.error)}</Notice>
          )}
          {available.map((option) => (
            <CheckboxField
              key={option.community.id}
              label={option.community.name}
              hint={optionHint(option)}
              disabled={option.outcome === null}
              checked={chosen.includes(option.community.id)}
              onChange={(event) => toggle(option.community.id, event.target.checked)}
            />
          ))}
          <button type="submit" disabled={chosen.length === 0 || share.isPending}>
            {share.isPending ? "Sharing…" : "Share"}
          </button>
        </form>
      )}
    </section>
  );
}
