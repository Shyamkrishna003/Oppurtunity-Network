import { Link, useNavigate, useParams } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useMe } from "../features/auth/api";
import { EventForm } from "../features/events/EventForm";
import { useOpportunity, useUpdateOpportunity } from "../features/opportunities/api";
import { JobForm } from "../features/opportunities/JobForm";
import type { OpportunityInput } from "../features/opportunities/types";
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
        <h1>Edit</h1>
        <Notice kind="error">{errorMessage(opportunity.error)}</Notice>
        <Link to="/my/opportunities">Back to my opportunities</Link>
      </>
    );
  }

  const data = opportunity.data;
  const isEvent = data.type === "EVENT";
  const kind = isEvent ? "event" : "job";
  const { can_manage: canManage, editable_fields: editable } = data.viewer;
  if (!canManage || (editable !== null && editable.length === 0)) {
    return (
      <>
        <h1>Edit {kind}</h1>
        <Notice kind="error">
          {canManage
            ? `This ${kind} is closed and can no longer be edited.`
            : `You cannot edit this ${kind}.`}
        </Notice>
        <Link to={back}>Back to the {kind}</Link>
      </>
    );
  }

  const form = {
    opportunity: data,
    hasOrganization: data.organization !== null,
    editableFields: editable,
    canCreateSkills: me.data?.email_verified ?? false,
    submitLabel: "Save",
    onCancel: () => void navigate(back),
    onSubmit: async (input: Partial<OpportunityInput>) => {
      await update.mutateAsync(input);
      await navigate(back);
    },
  };

  return (
    <>
      <h1>Edit {kind}</h1>
      <section className="card">
        {isEvent ? <EventForm {...form} /> : <JobForm {...form} />}
      </section>
    </>
  );
}
