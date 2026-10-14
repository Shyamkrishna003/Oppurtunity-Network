import { useOpportunityNumbers } from "./api";
import { FunnelChart } from "./FunnelChart";
import type { OpportunityDetail, OpportunityNumbers } from "./types";

const number = new Intl.NumberFormat();
const dayFormat = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

/** A calendar day ("2026-10-14") in words. Read as a local date: read as an instant it
 *  would be the day before for anyone west of Greenwich. */
function formatDate(day: string): string {
  return dayFormat.format(new Date(`${day}T00:00:00`));
}

/** Views on each of the last days as thin bars. One series, so no legend: the heading
 *  names it. The same numbers are in a table for anyone who cannot see the bars. */
function ViewsByDay({ days }: { days: OpportunityNumbers["views_by_day"] }) {
  const busiest = Math.max(0, ...days.map((day) => day.views));
  // Never divide by zero when nobody has looked yet.
  const most = Math.max(1, busiest);
  const first = days[0];
  const last = days[days.length - 1];
  if (!first || !last) {
    return null;
  }
  return (
    <figure className="daybars">
      <figcaption>Views a day, last {days.length} days</figcaption>
      <div className="daybars-plot" aria-hidden="true">
        {days.map((day) => (
          <span
            key={day.date}
            className="daybars-day"
            title={`${formatDate(day.date)}: ${number.format(day.views)}`}
          >
            <span
              className="daybars-bar"
              // A quiet day keeps a sliver, so the row of days stays readable.
              style={{ height: `${String(Math.max(3, (day.views / most) * 100))}%` }}
            />
          </span>
        ))}
      </div>
      <div className="daybars-axis muted" aria-hidden="true">
        <span>{formatDate(first.date)}</span>
        <span>Most in a day: {number.format(busiest)}</span>
        <span>{formatDate(last.date)}</span>
      </div>
      <table className="visually-hidden">
        <caption>Views a day</caption>
        <thead>
          <tr>
            <th scope="col">Day</th>
            <th scope="col">Views</th>
          </tr>
        </thead>
        <tbody>
          {days.map((day) => (
            <tr key={day.date}>
              <th scope="row">{formatDate(day.date)}</th>
              <td>{day.views}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

/** How an opportunity is doing, for the people who manage it. Says nothing while it
 *  loads or if it cannot be had: the page is about the opportunity, not its numbers. */
export function NumbersPanel({ opportunity }: { opportunity: OpportunityDetail }) {
  const query = useOpportunityNumbers(opportunity.id, opportunity.status !== "DRAFT");
  if (!query.data) {
    return null;
  }
  const numbers = query.data;
  const figures: [label: string, value: number][] = [
    ["People who opened it", numbers.views],
    ["Saved it", numbers.saves],
    opportunity.type === "EVENT"
      ? ["Places held", numbers.registrations]
      : ["Applications", numbers.applications],
  ];
  if (opportunity.type === "JOB") {
    figures.push(["Referrals", numbers.referrals]);
  }
  return (
    <section className="card" aria-labelledby="numbers-heading">
      <h2 id="numbers-heading">How it is doing</h2>
      <p className="muted">
        Only you and the others who manage this can see these. A person counts once a day, and your
        own visits are not counted.
      </p>
      <dl className="figures">
        {figures.map(([label, value]) => (
          <div key={label} className="figure">
            <dt>{label}</dt>
            <dd>{number.format(value)}</dd>
          </div>
        ))}
      </dl>
      <ViewsByDay days={numbers.views_by_day} />
      {numbers.funnels.map((funnel) => (
        <FunnelChart key={funnel.name} funnel={funnel} />
      ))}
    </section>
  );
}
