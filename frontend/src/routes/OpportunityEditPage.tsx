import { Link, useNavigate, useParams } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useMe } from "../features/auth/api";
import { useOpportunity, useUpdateOpportunity } from "../features/opportunities/api";
import { JobForm } from "../features/opportunities/JobForm";
import { errorMessage } from "../services/formErrors";

export function OpportunityEditPage() {
  const { opportunityId = "" } = useParams();
  const me = useMe();
  const navigate = useNavigate();
  const opportunity = useOpportunity(opportunityId);
  const update = useUpdateOpportunity(opportunityId);
  const back = `/opportunities/${opportunityId}`;

  if (opportunity.isPending) {
    return <Splash />;
  }
  if (opportunity.isError) {
    return (
      <>
        <h1>Edit job</h1>
        <Notice kind="error">{errorMessage(opportunity.error)}</Notice>
        <Link to="/my/opportunities">Back to my opportunities</Link>
      </>
    );
  }

  const data = opportunity.data;
  const { can_manage: canManage, editable_fields: editable } = data.viewer;
  if (!canManage || (editable !== null && editable.length === 0)) {
    return (
      <>
        <h1>Edit job</h1>
        <Notice kind="error">
          {canManage
            ? "This job is closed and can no longer be edited."
            : "You cannot edit this job."}
        </Notice>
        <Link to={back}>Back to the job</Link>
      </>
    );
  }

  return (
    <>
      <h1>Edit job</h1>
      <section className="card">
        <JobForm
          opportunity={data}
          hasOrganization={data.organization !== null}
          editableFields={editable}
          canCreateSkills={me.data?.email_verified ?? false}
          submitLabel="Save"
          onCancel={() => void navigate(back)}
          onSubmit={async (input) => {
            await update.mutateAsync(input);
            await navigate(back);
          }}
        />
      </section>
    </>
  );
}
