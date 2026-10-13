import { useState } from "react";

import { useMyRegistration } from "./api";
import { QrCode } from "./QrCode";

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

/** What someone holding a place shows at the door: their check-in code, or the fact that
 *  they are already in. Renders nothing while there is nothing to show. */
export function Ticket({ eventId }: { eventId: string }) {
  const mine = useMyRegistration(eventId, true);
  const [shown, setShown] = useState(false);
  const registration = mine.data;

  if (registration?.checked_in_at) {
    return (
      <p>
        <span className="badge badge-ok">Checked in</span>{" "}
        {timeFormat.format(new Date(registration.checked_in_at))}
      </p>
    );
  }
  if (!registration?.checkin_code) {
    return null;
  }
  return (
    <div className="ticket">
      <button type="button" aria-expanded={shown} onClick={() => setShown((value) => !value)}>
        {shown ? "Hide check-in code" : "Show check-in code"}
      </button>
      {shown && (
        <>
          <QrCode value={registration.checkin_code} label="Your check-in code" />
          <p className="muted">
            Show this at the door. It is yours alone, so do not share a picture of it.
          </p>
        </>
      )}
    </div>
  );
}
