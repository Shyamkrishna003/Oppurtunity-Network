import type { ReactNode } from "react";
import { Link } from "react-router";

import { Avatar } from "../../components/Avatar";
import { EXPERIENCE_LEVELS, formatLocation, WORK_MODES } from "../profile/labels";
import { formatDate, formatSalary } from "./format";
import { EMPLOYMENT_TYPE_LABELS, type Opportunity } from "./types";

const DAY_MS = 24 * 60 * 60 * 1000;

/** A nudge for an open opportunity whose deadline is within a week; otherwise nothing. */
function timeLeft(opportunity: Opportunity): string | null {
  if (opportunity.status !== "PUBLISHED" || !opportunity.deadline) {
    return null;
  }
  const days = Math.ceil((new Date(opportunity.deadline).getTime() - Date.now()) / DAY_MS);
  if (days < 1 || days > 7) {
    return null;
  }
  return days === 1 ? "Last day" : `${String(days)} days left`;
}

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
  const hurry = timeLeft(opportunity);

  return (
    <li className="opportunity-card">
      <div className="entry">
        <div className="opportunity-main">
          <Avatar
            name={owner ?? opportunity.title}
            url={opportunity.posted_by?.avatar_url ?? null}
            size={44}
            square={Boolean(opportunity.organization)}
          />
          <div>
            <Link to={`/opportunities/${opportunity.id}`} className="opportunity-title">
              <strong>{opportunity.title}</strong>
            </Link>
            {badge}
            {owner && <div className="opportunity-owner">{owner}</div>}
            {facts.length > 0 && <div className="muted">{facts.join(" · ")}</div>}
            {opportunity.deadline && (
              <div className="muted">
                Apply by {formatDate(opportunity.deadline)}
                {hurry && <span className="hurry">{hurry}</span>}
              </div>
            )}
          </div>
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
