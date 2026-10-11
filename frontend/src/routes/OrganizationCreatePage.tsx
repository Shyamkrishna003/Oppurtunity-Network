import { Link, useNavigate } from "react-router";

import { Notice } from "../components/Notice";
import { useMe } from "../features/auth/api";
import { useCreateOrganization } from "../features/organizations/api";
import { OrganizationForm } from "../features/organizations/OrganizationForm";

export function OrganizationCreatePage() {
  const me = useMe();
  const create = useCreateOrganization();
  const navigate = useNavigate();

  return (
    <>
      <h1>Create an organization</h1>
      <p className="muted">
        You will be its owner. You can invite colleagues and give them roles afterwards.
      </p>
      {me.data && !me.data.email_verified ? (
        <Notice kind="error">
          Confirm your email address before creating an organization. Use the link we emailed you,
          or request a new one from the banner above.
        </Notice>
      ) : (
        <section className="card">
          <OrganizationForm
            submitLabel="Create organization"
            onSubmit={async (values) => {
              const organization = await create.mutateAsync(values);
              await navigate(`/organizations/${organization.id}`);
            }}
          />
        </section>
      )}
      <p className="form-links">
        <Link to="/organizations">Back to organizations</Link>
      </p>
    </>
  );
}
