import { useState } from "react";
import { Link } from "react-router";

import { Avatar } from "../../components/Avatar";
import { Confetti } from "../../components/Confetti";
import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { ApiError } from "../../services/http";
import { useMe, useSessionStatus } from "../auth/api";
import type { OpportunityDetail } from "../opportunities/types";
import { useAttendees, useCancelRegistration, useRegister } from "./api";
import { Ticket } from "./Ticket";

function Attendees({ eventId, count }: { eventId: string; count: number }) {
  const attendees = useAttendees(eventId, count > 0);
  // The organizers may keep the list to themselves or to people going: then say nothing.
  if (!attendees.isSuccess || attendees.data.length === 0) {
    return null;
  }
  const hidden = count - attendees.data.length;
  return (
    <>
      <h3>Who is going</h3>
      <ul className="people" aria-label="People going">
        {attendees.data.map((person) => (
          <li key={person.id}>
            <Link to={`/users/${person.id}`} className="person">
              <Avatar name={person.display_name} url={person.avatar_url} size={28} />
              {person.display_name}
            </Link>
          </li>
        ))}
      </ul>
      {hidden > 0 && <p className="muted">and {hidden} more.</p>}
    </>
  );
}

/** The "Registration" section of an event page, in whichever form fits the viewer. */
export function RegisterPanel({ opportunity }: { opportunity: OpportunityDetail }) {
  const session = useSessionStatus();
  const me = useMe();
  const register = useRegister(opportunity.id);
  const cancel = useCancelRegistration(opportunity.id);
  const [celebrate, setCelebrate] = useState(false);
  const { event, viewer } = opportunity;
  if (!event || event.event_status === "") {
    return null; // a job, or a draft nobody can register for yet
  }

  const { registration, can_register: canRegister } = viewer;
  const active = registration !== null && registration.status !== "CANCELLED";
  const upcoming = event.event_status !== "COMPLETED" && event.event_status !== "CANCELLED";
  const full = event.capacity !== null && event.confirmed_count >= event.capacity;
  const failure = register.error ?? cancel.error;
  const closedMeanwhile = failure instanceof ApiError && failure.code === "registration_closed";
  const busy = register.isPending || cancel.isPending;

  const registerButton = (
    <button
      type="button"
      className="primary"
      disabled={busy}
      onClick={() =>
        register.mutate(undefined, {
          onSuccess: (result) => setCelebrate(result.status === "CONFIRMED"),
        })
      }
    >
      {register.isPending ? "Registering…" : full ? "Join the waitlist" : "Register"}
    </button>
  );

  let content;
  if (active) {
    const going = registration.status === "CONFIRMED";
    content = (
      <>
        <p>
          <span className={going ? "badge badge-ok" : "badge"}>
            {going ? "You are going" : "On the waitlist"}
          </span>{" "}
          {going
            ? "Your place is kept."
            : `You are number ${String(registration.waitlist_position ?? 1)} in the queue. You get a place, and a message, as soon as one frees up.`}
        </p>
        {going && <Ticket eventId={opportunity.id} />}
        {upcoming && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              const question = going
                ? "Cancel your registration? Your place goes to the next person waiting."
                : "Leave the waitlist? You lose your place in the queue.";
              if (window.confirm(question)) {
                setCelebrate(false);
                cancel.mutate();
              }
            }}
          >
            {cancel.isPending
              ? "Cancelling…"
              : going
                ? "Cancel registration"
                : "Leave the waitlist"}
          </button>
        )}
      </>
    );
  } else if (!upcoming) {
    content = null;
  } else if (session === "anonymous") {
    content = (
      <>
        <p>Sign in to register for this event.</p>
        <Link
          to={`/login?next=${encodeURIComponent(`/opportunities/${opportunity.id}`)}`}
          className="button primary"
        >
          Sign in to register
        </Link>
      </>
    );
  } else if (!canRegister) {
    content = (
      <p className="muted">
        {event.event_status === "SCHEDULED"
          ? "Registration has not opened yet."
          : "Registration for this event is closed."}
      </p>
    );
  } else if (me.data && !me.data.email_verified) {
    content = (
      <Notice kind="error">
        Confirm your email address before registering. Use the link we sent you, or ask for a new
        one at the top of this page.
      </Notice>
    );
  } else {
    content = (
      <>
        <p>
          {full
            ? "Every place is taken. Join the waitlist and you get the next one that frees up."
            : registration
              ? "You cancelled your registration. You can register again."
              : "Save your place. You can cancel any time before it starts."}
        </p>
        {registerButton}
      </>
    );
  }

  return (
    <section className="card" aria-labelledby="registration-heading">
      {celebrate && <Confetti />}
      <h2 id="registration-heading">Registration</h2>
      {failure && (
        <Notice kind="error">
          {closedMeanwhile ? "Registration for this event has just closed." : errorMessage(failure)}
        </Notice>
      )}
      {content}
      <Attendees eventId={opportunity.id} count={event.confirmed_count} />
    </section>
  );
}
