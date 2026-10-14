import { Link, useParams } from "react-router";

import { AuditTrail } from "../features/audit/AuditTrail";

const WORDS = {
  organization: {
    back: "Back to the organization",
    path: "organizations",
    covers:
      "Changes to the organization and its members, its opportunities, and what was done with the applications and registrations it received.",
    owners: "the organization's owners",
  },
  community: {
    back: "Back to the community",
    path: "communities",
    covers:
      "Changes to the community, its rules and its members, and what its moderators decided about shared opportunities and reports. Who reported something is never recorded here.",
    owners: "the community's owners",
  },
} as const;

/** What has been done in an organization or a community, for its owners. */
export function TenantAuditPage({ kind }: { kind: keyof typeof WORDS }) {
  const { organizationId, communityId } = useParams();
  const id = (kind === "organization" ? organizationId : communityId) ?? "";
  const words = WORDS[kind];
  return (
    <>
      <p>
        <Link to={`/${words.path}/${id}`}>{words.back}</Link>
      </p>
      <h1>Activity log</h1>
      <p className="muted">{words.covers} Newest first; nothing here can be changed.</p>
      <section className="card" aria-label="Activity log">
        <AuditTrail scope={{ kind, id }} forWhom={words.owners} />
      </section>
    </>
  );
}
