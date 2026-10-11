import type { Match, MatchKind } from "./types";

const PHRASES: Record<MatchKind, (label: string) => string> = {
  skill: (label) => `you have ${label}`,
  interest: (label) => `you are interested in ${label}`,
  community: (label) => `shared in ${label}`,
  location: (label) => `in ${label}`,
  work_mode: (label) => `${label.toLowerCase()}, as you prefer`,
};

/** Every point of an opportunity's ranking, in words. Nothing shown means nothing matched. */
export function MatchReasons({ match }: { match: Match | null }) {
  if (!match || match.reasons.length === 0) {
    return null;
  }
  return (
    <p className="match-reasons">
      <strong>Why it fits:</strong>{" "}
      {match.reasons.map((reason) => PHRASES[reason.kind](reason.label)).join(" · ")}
    </p>
  );
}
