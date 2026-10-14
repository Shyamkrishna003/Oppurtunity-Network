import { useId } from "react";

import type { Funnel } from "./types";

const number = new Intl.NumberFormat();

const TITLES: Record<Funnel["name"], string> = {
  applications: "From opening it to being hired",
  referrals: "Referrals",
  registrations: "From opening it to coming",
};

const STEPS: Record<string, string> = {
  views: "Opened it",
  applied: "Applied",
  screening: "Screening",
  shortlisted: "Shortlisted",
  interview: "Interview",
  offer: "Offer",
  hired: "Hired",
  registered: "Registered",
  going: "Still holding a place",
  attended: "Came",
  requested: "Asked for a referral",
  accepted: "Accepted",
  referred: "Referred",
  joined: "Joined",
};

/**
 * One funnel as a list of steps, each with its number and a bar. Every value is written
 * out, so the bars only add a sense of proportion: one series, one colour, no legend.
 */
export function FunnelChart({ funnel }: { funnel: Funnel }) {
  const id = useId();
  const most = Math.max(1, ...funnel.steps.map((step) => step.count));
  return (
    <figure className="funnel" aria-labelledby={id}>
      <figcaption id={id}>{TITLES[funnel.name]}</figcaption>
      <ol>
        {funnel.steps.map((step, index) => {
          const before = funnel.steps[index - 1]?.count ?? 0;
          // Only where it means something: views started being counted later than
          // applications, so a step can be larger than the one before it.
          const kept =
            index > 0 && before > 0 && step.count <= before
              ? `${String(Math.round((step.count / before) * 100))}% of the step before`
              : "";
          return (
            <li key={step.key} title={kept || undefined}>
              <span className="funnel-label">{STEPS[step.key] ?? step.key}</span>
              <span className="funnel-track" aria-hidden="true">
                <span
                  className="funnel-bar"
                  style={{ width: `${String((step.count / most) * 100)}%` }}
                />
              </span>
              <span className="funnel-count">
                {number.format(step.count)}
                {kept && <span className="visually-hidden">, {kept}</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </figure>
  );
}
