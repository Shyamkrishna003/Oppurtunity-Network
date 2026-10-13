import { useState } from "react";
import { Link, useParams } from "react-router";

import { TextAreaField } from "../components/Field";
import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useReferral, useReferralAction } from "../features/referrals/api";
import {
  ENDORSEMENT_MAX,
  ENDORSEMENT_MIN,
  REFERRAL_STATUS_LABELS,
  referralBadgeClass,
  type ReferralAction,
  type ReferralDetail,
  type ReferralStep,
} from "../features/referrals/types";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

const STEP_TEXT: Record<ReferralStep["to_status"], string> = {
  REQUESTED: "Referral requested",
  ACCEPTED: "Request accepted",
  DECLINED: "Request declined",
  CANCELLED: "Request cancelled",
  EXPIRED: "Request expired without an answer",
  REFERRED: "Referral made",
  APPLICATION_SUBMITTED: "Application submitted",
  INTERVIEW: "Reached the interview stage",
  OFFER: "Received an offer",
  JOINED: "Hired",
  CLOSED: "Closed",
};

const BUTTON_LABELS: Record<Exclude<ReferralAction, "refer">, string> = {
  accept: "Accept",
  decline: "Decline",
  cancel: "Cancel request",
  back_out: "I can no longer refer them",
};

const CONFIRMATIONS: Partial<Record<ReferralAction, string>> = {
  decline: "Decline this request? It cannot be sent to you again for this job.",
  cancel: "Cancel this request? You cannot ask this person about this job again.",
  back_out: "Tell them you can no longer make this referral? This closes it.",
};

function ReferForm({ referral }: { referral: ReferralDetail }) {
  const act = useReferralAction(referral.id);
  const [note, setNote] = useState("");
  const tooShort = note.trim().length < ENDORSEMENT_MIN;
  const serverError =
    act.error instanceof ApiError ? act.error.fieldErrors.endorsement_note?.join(" ") : undefined;

  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!tooShort) {
          act.mutate({ action: "refer", endorsementNote: note.trim() });
        }
      }}
    >
      {act.isError && !serverError && <Notice kind="error">{errorMessage(act.error)}</Notice>}
      <TextAreaField
        label={`Why you recommend ${referral.requester.display_name}`}
        hint={`Shown to the people hiring for this job, not to ${referral.requester.display_name}. At least ${ENDORSEMENT_MIN} characters.`}
        rows={5}
        maxLength={ENDORSEMENT_MAX}
        value={note}
        onChange={(event) => setNote(event.target.value)}
        error={serverError}
      />
      <button type="submit" className="primary" disabled={tooShort || act.isPending}>
        {act.isPending ? "Sending…" : "Make the referral"}
      </button>
    </form>
  );
}

function Actions({ referral }: { referral: ReferralDetail }) {
  const act = useReferralAction(referral.id);
  const { actions } = referral.viewer;
  const buttons = actions.filter((action) => action !== "refer") as Exclude<
    ReferralAction,
    "refer"
  >[];

  if (actions.length === 0) {
    return null;
  }
  return (
    <section className="card" aria-labelledby="actions-heading">
      <h2 id="actions-heading">{referral.viewer.is_referrer ? "Your answer" : "Your request"}</h2>
      {actions.includes("refer") && <ReferForm referral={referral} />}
      {act.isError && <Notice kind="error">{errorMessage(act.error)}</Notice>}
      <div className="button-row">
        {buttons.map((action) => (
          <button
            key={action}
            type="button"
            className={action === "accept" ? "primary" : undefined}
            disabled={act.isPending}
            onClick={() => {
              const question = CONFIRMATIONS[action];
              if (!question || window.confirm(question)) {
                act.mutate({ action });
              }
            }}
          >
            {BUTTON_LABELS[action]}
          </button>
        ))}
      </div>
    </section>
  );
}

/** What the status means for the person reading, in a sentence. */
function explanation(referral: ReferralDetail): string | null {
  const { viewer, status, requester, referrer } = referral;
  if (status === "REQUESTED") {
    const until = timeFormat.format(new Date(referral.expires_at));
    return viewer.is_referrer
      ? `${requester.display_name} is waiting for your answer. The request lapses on ${until}.`
      : `Waiting for ${referrer.display_name} to answer. The request lapses on ${until}.`;
  }
  if (status === "ACCEPTED") {
    return viewer.is_referrer
      ? "You agreed. The people hiring see nothing until you make the referral below."
      : `${referrer.display_name} agreed to refer you and still has to make the referral.`;
  }
  if (status === "REFERRED" && viewer.is_requester) {
    return "The referral is made. Apply to the job and it will be shown with your application.";
  }
  return null;
}

export function ReferralPage() {
  const { referralId = "" } = useParams();
  const referral = useReferral(referralId);

  if (referral.isPending) {
    return <Splash />;
  }
  if (referral.isError) {
    const notFound = referral.error instanceof ApiError && referral.error.status === 404;
    return (
      <>
        <h1>{notFound ? "Referral not found" : "Something went wrong"}</h1>
        <p className="muted">
          {notFound
            ? "This referral does not exist or is not available to you."
            : errorMessage(referral.error)}
        </p>
        {!notFound && (
          <button type="button" onClick={() => void referral.refetch()}>
            Try again
          </button>
        )}
      </>
    );
  }

  const data = referral.data;
  const { opportunity, requester, referrer, viewer } = data;
  const note = explanation(data);
  const heading = viewer.is_requester
    ? `Your referral request to ${referrer.display_name}`
    : viewer.is_referrer
      ? `Referral request from ${requester.display_name}`
      : `${referrer.display_name} referred ${requester.display_name}`;

  return (
    <>
      <div className="page-heading">
        <h1>{heading}</h1>
        <span className={referralBadgeClass(data.status)}>
          {REFERRAL_STATUS_LABELS[data.status]}
        </span>
      </div>
      <p>
        For <Link to={`/opportunities/${opportunity.id}`}>{opportunity.title}</Link>
        {opportunity.organization && <> at {opportunity.organization.name}</>}
      </p>
      {note && <p className="muted">{note}</p>}
      {data.application_id && (
        <p>
          <Link to={`/applications/${data.application_id}`}>
            {viewer.is_requester ? "View your application" : "View the application"}
          </Link>
        </p>
      )}

      {(viewer.is_requester || viewer.is_referrer) && (
        <section className="card" aria-labelledby="message-heading">
          <h2 id="message-heading">
            {viewer.is_requester ? "Your message" : `Message from ${requester.display_name}`}
          </h2>
          {data.message ? (
            <p className="prose">{data.message}</p>
          ) : (
            <p className="muted">No message was included.</p>
          )}
        </section>
      )}

      {data.endorsement_note && (
        <section className="card" aria-labelledby="endorsement-heading">
          <h2 id="endorsement-heading">
            {viewer.is_referrer
              ? "What you told the people hiring"
              : `What ${referrer.display_name} says`}
          </h2>
          <p className="prose">{data.endorsement_note}</p>
        </section>
      )}

      <Actions referral={data} />

      <section className="card" aria-labelledby="history-heading">
        <h2 id="history-heading">History</h2>
        <ol className="entry-list">
          {data.history.map((step) => (
            <li key={`${step.to_status}-${step.created_at}`} className="entry">
              <span>{STEP_TEXT[step.to_status]}</span>
              <time className="muted" dateTime={step.created_at}>
                {timeFormat.format(new Date(step.created_at))}
              </time>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
