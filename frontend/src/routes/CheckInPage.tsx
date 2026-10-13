import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { Avatar } from "../components/Avatar";
import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useCheckIn, useRegistrationSummary } from "../features/events/api";
import { CameraScanner } from "../features/events/CameraScanner";
import { useOpportunity } from "../features/opportunities/api";
import type { Person } from "../features/organizations/types";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

const clock = new Intl.DateTimeFormat(undefined, { timeStyle: "short" });

type Outcome =
  | { kind: "in"; person: Person; at: string }
  | { kind: "again"; at: string | null }
  | { kind: "refused"; message: string };

function Result({ outcome }: { outcome: Outcome }) {
  if (outcome.kind === "in") {
    return (
      <Notice kind="ok">
        <span className="person">
          <Avatar name={outcome.person.display_name} url={outcome.person.avatar_url} size={36} />
          <strong>{outcome.person.display_name}</strong>
        </span>{" "}
        is checked in.
      </Notice>
    );
  }
  if (outcome.kind === "again") {
    return (
      <Notice kind="error">
        This code was already used
        {outcome.at ? ` at ${clock.format(new Date(outcome.at))}` : ""}. Nobody was checked in
        again.
      </Notice>
    );
  }
  return <Notice kind="error">{outcome.message}</Notice>;
}

export function CheckInPage() {
  const { opportunityId = "" } = useParams();
  const event = useOpportunity(opportunityId);
  const summary = useRegistrationSummary(opportunityId);
  const checkIn = useCheckIn(opportunityId);
  const [code, setCode] = useState("");
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  if (event.isPending || summary.isPending) {
    return <Splash />;
  }
  if (event.isError || summary.isError) {
    const failure = event.error ?? summary.error;
    const denied =
      failure instanceof ApiError && (failure.status === 403 || failure.status === 404);
    return (
      <>
        <h1>{denied ? "Check-in not available" : "Something went wrong"}</h1>
        <p className="muted">
          {denied
            ? "This event does not exist, or you are not one of the people who run it."
            : errorMessage(failure)}
        </p>
      </>
    );
  }

  function submit(value: string) {
    const trimmed = value.trim();
    if (!trimmed || checkIn.isPending) {
      return;
    }
    checkIn.mutate(trimmed, {
      onSuccess: (result) => {
        setOutcome({ kind: "in", person: result.person, at: result.checked_in_at });
        setCode("");
      },
      onError: (error) => {
        if (error instanceof ApiError && error.code === "already_checked_in") {
          setOutcome({ kind: "again", at: error.fieldErrors.checked_in_at?.[0] ?? null });
        } else {
          setOutcome({ kind: "refused", message: errorMessage(error) });
        }
        setCode("");
      },
    });
  }

  const { counts, checked_in: checkedIn, checkin_open: open } = summary.data;
  return (
    <>
      <h1>Check-in</h1>
      <p>
        For <Link to={`/opportunities/${opportunityId}`}>{event.data.title}</Link>
      </p>
      <p>
        <strong>{checkedIn}</strong> of <strong>{counts.CONFIRMED}</strong> people going are checked
        in.
      </p>
      {!open && (
        <Notice kind="error">
          Check-in is not open right now. It opens two hours before the event starts and closes when
          it ends.
        </Notice>
      )}

      <section className="card" aria-label="Check someone in">
        {/* Announced as it changes, so someone scanning does not have to look away. */}
        <div aria-live="assertive">{outcome && <Result outcome={outcome} />}</div>
        <CameraScanner onCode={submit} />
        <form
          className="search-form"
          onSubmit={(submitted: FormEvent) => {
            submitted.preventDefault();
            submit(code);
          }}
        >
          <input
            aria-label="Check-in code"
            placeholder="Paste or scan a check-in code"
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            value={code}
            onChange={(changed) => setCode(changed.target.value)}
          />
          <button type="submit" className="primary" disabled={checkIn.isPending || !code.trim()}>
            {checkIn.isPending ? "Checking…" : "Check in"}
          </button>
        </form>
        <p className="muted">
          Each attendee has a code on the event&apos;s page. A code works once, and only for this
          event.
        </p>
      </section>
    </>
  );
}
