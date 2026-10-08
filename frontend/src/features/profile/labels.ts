import type { ExperienceLevel, ProfileVisibility, WorkMode } from "../auth/types";

export const WORK_MODES: Record<Exclude<WorkMode, "">, string> = {
  REMOTE: "Remote",
  HYBRID: "Hybrid",
  ONSITE: "On-site",
};

export const EXPERIENCE_LEVELS: Record<Exclude<ExperienceLevel, "">, string> = {
  INTERN: "Intern",
  ENTRY: "Entry level",
  MID: "Mid level",
  SENIOR: "Senior",
  LEAD: "Lead",
};

export const VISIBILITIES: Record<ProfileVisibility, string> = {
  PUBLIC: "Everyone signed in",
  CONNECTIONS: "My connections only",
  COMMUNITY: "Members of my communities",
  PRIVATE: "Only me",
};

export function formatLocation(parts: { city: string; region: string; country_code: string }) {
  return [parts.city, parts.region, parts.country_code].filter(Boolean).join(", ");
}

const monthYear = new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" });

export function formatPeriod(start: string, end: string | null): string {
  const from = monthYear.format(new Date(`${start}T00:00:00`));
  const to = end ? monthYear.format(new Date(`${end}T00:00:00`)) : "Present";
  return `${from} – ${to}`;
}
