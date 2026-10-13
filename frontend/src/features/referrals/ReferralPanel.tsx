import { useState } from "react";
import { Link } from "react-router";

import { Avatar } from "../../components/Avatar";
import { TextAreaField } from "../../components/Field";
import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { useMe } from "../auth/api";
import type { OpportunityDetail } from "../opportunities/types";
import { useEligibleReferrers, useMyReferralsForJob, useRequestReferral } from "./api";
import { MESSAGE_MAX, REFERRAL_STATUS_LABELS, referralBadgeClass } from "./types";

function Chooser({ opportunityId, onDone }: { opportunityId: string; onDone: () => void }) {
  const eligible = useEligibleReferrers(opportunityId, true);
  const request = useRequestReferral(opportunityId);
  const [referrerId, setReferrerId] = useState("");
  const [message, setMessage] = useState("");

  if (eligible.isPending) {
    return (
      <p className="muted" role="status">
        Looking through your connections…
      </p>
    );
  }
  if (eligible.isError) {
    return (
      <Notice kind="error">
        <p>{errorMessage(eligible.error)}</p>
        <button type="button" onClick={() => void eligible.refetch()}>
          Try again
        </button>
      </Notice>
    );
  }
  const { referrers, remaining } = eligible.data;
  if (remaining === 0) {
    return (
      <p className="muted">
        You already have as many requests open for this job as you can have at one time.
      </p>
    );
  }
  if (referrers.length === 0) {
    return (
      <p className="muted">
        None of your connections can be asked about this job. Only connections who show that they
        work here, and take referral requests, appear.{" "}
        <Link to="/connections">Your connections</Link>
      </p>
    );
  }

  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (referrerId) {
          request.mutate({ referrerId, message: message.trim() }, { onSuccess: onDone });
        }
      }}
    >
      {request.isError && <Notice kind="error">{errorMessage(request.error)}</Notice>}
      <fieldset className="plain-fieldset field">
        <legend>Who would you like to ask?</legend>
        {referrers.map((person) => (
          <label key={person.id} className="person choice">
            <input
              type="radio"
              name="referrer"
              value={person.id}
              checked={referrerId === person.id}
              onChange={() => setReferrerId(person.id)}
            />
            <Avatar name={person.display_name} url={person.avatar_url} size={32} />
            <span>
              {person.display_name}
              {person.headline && <span className="muted"> · {person.headline}</span>}
            </span>
          </label>
        ))}
      </fieldset>
      <TextAreaField
        label="Message to them (optional)"
        hint="Only the person you ask reads this."
        rows={4}
        maxLength={MESSAGE_MAX}
        value={message}
        onChange={(event) => setMessage(event.target.value)}
      />
      <div className="button-row">
        <button type="submit" className="primary" disabled={!referrerId || request.isPending}>
          {request.isPending ? "Sending…" : "Send request"}
        </button>
        <button type="button" onClick={onDone}>
          Not now
        </button>
      </div>
    </form>
  );
}

/**
 * The "Referral" section of a job page: the requests the viewer already made for this job,
 * and a way to ask one of their own connections. Renders nothing when referrals are not
 * available to them here and they never asked for one.
 */
export function ReferralPanel({ opportunity }: { opportunity: OpportunityDetail }) {
  const me = useMe();
  const canRequest = opportunity.viewer.can_request_referral;
  const signedIn = Boolean(me.data);
  const [choosing, setChoosing] = useState(false);
  // Referrals only exist for an organization's jobs, so nothing is asked about any other.
  const mine = useMyReferralsForJob(
    opportunity.id,
    signedIn && opportunity.type === "JOB" && opportunity.organization !== null,
  );
  const requests = mine.data?.pages.flatMap((page) => page.results) ?? [];

  if (!signedIn || (!canRequest && requests.length === 0)) {
    return null;
  }
  const verified = me.data?.email_verified ?? false;

  return (
    <section className="card" aria-labelledby="referral-heading">
      <h2 id="referral-heading">Referral</h2>
      {requests.length > 0 && (
        <ul className="entry-list">
          {requests.map((referral) => (
            <li key={referral.id} className="entry">
              <span>
                <Link to={`/referrals/${referral.id}`}>Asked {referral.referrer.display_name}</Link>
              </span>
              <span className={referralBadgeClass(referral.status)}>
                {REFERRAL_STATUS_LABELS[referral.status]}
              </span>
            </li>
          ))}
        </ul>
      )}
      {canRequest && !choosing && (
        <>
          {requests.length === 0 && (
            <p>
              Know someone who works here? A referral from a connection is shown to the people
              hiring, next to your application.
            </p>
          )}
          {verified ? (
            <button type="button" onClick={() => setChoosing(true)}>
              {requests.length === 0 ? "Ask for a referral" : "Ask someone else"}
            </button>
          ) : (
            <p className="muted">Confirm your email address to ask for a referral.</p>
          )}
        </>
      )}
      {canRequest && choosing && (
        <Chooser opportunityId={opportunity.id} onDone={() => setChoosing(false)} />
      )}
    </section>
  );
}
