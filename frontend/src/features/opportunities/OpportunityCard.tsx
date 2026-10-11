import type { ReactNode } from "react";
import { Link } from "react-router";

import { EXPERIENCE_LEVELS, formatLocation, WORK_MODES } from "../profile/labels";
import { formatDate, formatSalary } from "./format";
import { EMPLOYMENT_TYPE_LABELS, type Opportunity } from "./types";

/**
 * One opportunity in a list. `actions` is for controls that belong to the list's owner;
 * `children` go under the card, for whatever that list adds about each opportunity.
 */
export function OpportunityCard({
  opportunity,
  badge,
  actions,
  children,
}: {
  opportunity: Opportunity;
  badge?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  const { job } = opportunity;
  const owner = opportunity.organization?.name ?? opportunity.posted_by?.display_name;
  const facts = [
    job.employment_type && EMPLOYMENT_TYPE_LABELS[job.employment_type],
    job.experience_level && EXPERIENCE_LEVELS[job.experience_level],
    opportunity.work_mode && WORK_MODES[opportunity.work_mode],
    formatLocation(opportunity),
    formatSalary(job),
  ].filter(Boolean);

  return (
    <li className="opportunity-card">
      <div className="entry">
        <div>
          <Link to={`/opportunities/${opportunity.id}`}>
            <strong>{opportunity.title}</strong>
          </Link>
          {badge}
          {owner && <div>{owner}</div>}
          {facts.length > 0 && <div className="muted">{facts.join(" · ")}</div>}
          {opportunity.deadline && (
            <div className="muted">Apply by {formatDate(opportunity.deadline)}</div>
          )}
        </div>
        {actions && <div className="button-row">{actions}</div>}
      </div>
      {opportunity.skills.length > 0 && (
        <ul className="chips" aria-label={`Skills for ${opportunity.title}`}>
          {opportunity.skills.map((skill) => (
            <li key={skill.id} className="chip">
              {skill.name}
            </li>
          ))}
        </ul>
      )}
      {children}
    </li>
  );
}
