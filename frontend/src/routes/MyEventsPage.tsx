import { Link } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useMyEvents, type MyEvent } from "../features/events/api";
import { formatEventTime } from "../features/events/time";
import { EVENT_FORMAT_LABELS } from "../features/opportunities/types";
import { errorMessage } from "../services/formErrors";

function Row({ item }: { item: MyEvent }) {
  const { event } = item;
  const going = item.status === "CONFIRMED";
  const where = [
    event.format && EVENT_FORMAT_LABELS[event.format],
    [event.venue, event.city].filter(Boolean).join(", "),
  ].filter(Boolean);
  const off = event.event_status === "CANCELLED";
  return (
    <li className="entry">
      <div>
        <Link to={`/opportunities/${event.id}`}>
          <strong>{event.title}</strong>
        </Link>
        <div>{formatEventTime(event)}</div>
        <div className="muted">
          {event.organization ? `${event.organization.name} · ` : ""}
          {where.join(" · ")}
        </div>
      </div>
      <span className={going && !off ? "badge badge-ok" : off ? "badge badge-error" : "badge"}>
        {off ? "Cancelled" : going ? "Going" : "On the waitlist"}
      </span>
    </li>
  );
}

export function MyEventsPage() {
  const events = useMyEvents();

  if (events.isPending) {
    return <Splash />;
  }
  return (
    <>
      <h1>My events</h1>
      <p className="muted">Events you are going to or waiting for, soonest first.</p>
      <section className="card" aria-label="Your events">
        {events.isError ? (
          <Notice kind="error">
            <p>{errorMessage(events.error)}</p>
            <button type="button" onClick={() => void events.refetch()}>
              Try again
            </button>
          </Notice>
        ) : events.data.length === 0 ? (
          <p className="muted">
            You have not registered for anything yet.{" "}
            <Link to="/opportunities?type=EVENT">Find an event</Link>
          </p>
        ) : (
          <ul className="entry-list">
            {events.data.map((item) => (
              <Row key={item.id} item={item} />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
