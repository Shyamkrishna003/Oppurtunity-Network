import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { Notice } from "../components/Notice";
import { useMe } from "../features/auth/api";
import { useCreateOpportunity } from "../features/opportunities/api";
import { JobForm } from "../features/opportunities/JobForm";
import type { OpportunityInput } from "../features/opportunities/types";
import { useMyOrganizations } from "../features/organizations/api";

const POSTING_ROLES = ["OWNER", "ADMIN", "RECRUITER"];

export function OpportunityCreatePage() {
  const me = useMe();
  const navigate = useNavigate();
  const create = useCreateOpportunity();
  const organizations = useMyOrganizations();
  const [organizationId, setOrganizationId] = useState("");

  // Only organizations where the user may post; the server checks this again.
  const postable = (organizations.data ?? []).filter((item) => POSTING_ROLES.includes(item.role));

  return (
    <>
      <h1>Post a job</h1>
      <p className="muted">
        It is saved as a draft first. You can come back to it, and nobody else sees it until you
        publish.
      </p>
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
          <JobForm
            // The audience choices depend on who is posting, so start the form afresh.
            key={organizationId}
            hasOrganization={organizationId !== ""}
            editableFields={null}
            canCreateSkills={me.data?.email_verified ?? false}
            submitLabel="Save draft"
            onSubmit={async (input) => {
              const created = await create.mutateAsync({
                ...(input as OpportunityInput),
                type: "JOB",
                organization_id: organizationId || null,
              });
              await navigate(`/opportunities/${created.id}`);
            }}
          />
        </section>
      )}
      <p className="form-links">
        <Link to="/my/opportunities">Back to my opportunities</Link>
      </p>
    </>
  );
}
