import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { Notice } from "../components/Notice";
import { useMe } from "../features/auth/api";
import { EventForm } from "../features/events/EventForm";
import { useCreateOpportunity } from "../features/opportunities/api";
import { JobForm } from "../features/opportunities/JobForm";
import type { OpportunityInput } from "../features/opportunities/types";
import { useMyOrganizations } from "../features/organizations/api";

const POSTING_ROLES = ["OWNER", "ADMIN", "RECRUITER"];

export function OpportunityCreatePage() {
  const me = useMe();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const create = useCreateOpportunity();
  const organizations = useMyOrganizations();
  const [organizationId, setOrganizationId] = useState("");
  // Which kind is being posted lives in the address, so either can be linked to.
  const isEvent = params.get("type") === "event";

  // Only organizations where the user may post; the server checks this again.
  const postable = (organizations.data ?? []).filter((item) => POSTING_ROLES.includes(item.role));

  const form = {
    hasOrganization: organizationId !== "",
    editableFields: null,
    canCreateSkills: me.data?.email_verified ?? false,
    submitLabel: "Save draft",
    onSubmit: async (input: Partial<OpportunityInput>) => {
      const created = await create.mutateAsync({
        ...(input as OpportunityInput),
        type: isEvent ? "EVENT" : "JOB",
        organization_id: organizationId || null,
      });
      await navigate(`/opportunities/${created.id}`);
    },
  };

  return (
    <>
      <h1>{isEvent ? "Host an event" : "Post a job"}</h1>
      <p className="muted">
        It is saved as a draft first. You can come back to it, and nobody else sees it until you
        publish.
      </p>
      <nav aria-label="What you are posting">
        <ul className="stage-tabs">
          <li>
            <Link to="/opportunities/new" aria-current={isEvent ? undefined : "page"}>
              A job
            </Link>
          </li>
          <li>
            <Link to="/opportunities/new?type=event" aria-current={isEvent ? "page" : undefined}>
              An event
            </Link>
          </li>
        </ul>
      </nav>
      {me.data && !me.data.email_verified ? (
        <Notice kind="error">
          Confirm your email address before posting. Use the link we emailed you, or request a new
          one from the banner above.
        </Notice>
      ) : (
        <section className="card">
          {postable.length > 0 && (
            <div className="field">
              <label htmlFor="post-as">Post as</label>
              <select
                id="post-as"
                value={organizationId}
                onChange={(event) => setOrganizationId(event.target.value)}
              >
                <option value="">Myself</option>
                {postable.map(({ organization }) => (
                  <option key={organization.id} value={organization.id}>
                    {organization.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          {/* Keyed by who is posting: the audience choices depend on it, so start afresh. */}
          {isEvent ? (
            <EventForm key={organizationId} {...form} />
          ) : (
            <JobForm key={organizationId} {...form} />
          )}
        </section>
      )}
      <p className="form-links">
        <Link to="/my/opportunities">Back to my opportunities</Link>
      </p>
    </>
  );
}
