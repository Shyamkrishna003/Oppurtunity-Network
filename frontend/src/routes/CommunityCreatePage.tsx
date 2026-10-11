import { Link, useNavigate } from "react-router";

import { Notice } from "../components/Notice";
import { useMe } from "../features/auth/api";
import { useCreateCommunity } from "../features/communities/api";
import { CommunityForm } from "../features/communities/CommunityForm";

export function CommunityCreatePage() {
  const me = useMe();
  const create = useCreateCommunity();
  const navigate = useNavigate();

  return (
    <>
      <h1>Create a community</h1>
      <p className="muted">
        You will be its owner. You can invite people, appoint admins and moderators, and set rules
        afterwards.
      </p>
      {me.data && !me.data.email_verified ? (
        <Notice kind="error">
          Confirm your email address before creating a community. Use the link we emailed you, or
          request a new one from the banner above.
        </Notice>
      ) : (
        <section className="card">
          <CommunityForm
            submitLabel="Create community"
            onSubmit={async (values) => {
              const community = await create.mutateAsync(values);
              await navigate(`/communities/${community.id}`);
            }}
          />
        </section>
      )}
      <p className="form-links">
        <Link to="/communities">Back to communities</Link>
      </p>
    </>
  );
}
