import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { CheckboxField } from "../components/Field";
import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useSessionStatus } from "../features/auth/api";
import {
  useLeaveOrganization,
  useOrganization,
  useSetMembershipVisibility,
  useUpdateOrganization,
} from "../features/organizations/api";
import { ReportButton } from "../features/moderation/ReportButton";
import { InvitationPanel } from "../features/organizations/InvitationPanel";
import { MemberList } from "../features/organizations/MemberList";
import { OrganizationForm } from "../features/organizations/OrganizationForm";
import { ROLE_LABELS, type OrganizationDetail } from "../features/organizations/types";
import { formatLocation } from "../features/profile/labels";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

function YourMembership({ organization }: { organization: OrganizationDetail }) {
  const { viewer } = organization;
  const navigate = useNavigate();
  const leave = useLeaveOrganization(organization.id);
  const setVisibility = useSetMembershipVisibility(organization.id);
  const failure = leave.error ?? setVisibility.error;

  if (!viewer.role || !viewer.membership_id) {
    return null;
  }
  const membershipId = viewer.membership_id;
  return (
    <section className="card" aria-labelledby="membership-heading">
      <h2 id="membership-heading">Your membership</h2>
      {failure && <Notice kind="error">{errorMessage(failure)}</Notice>}
      <p>
        You are {viewer.role === "MEMBER" ? "a" : "an"}{" "}
        <strong>{ROLE_LABELS[viewer.role].toLowerCase()}</strong> of this organization.
      </p>
      <CheckboxField
        label="Show me in the member list to people outside the organization"
        checked={viewer.is_public ?? true}
        disabled={setVisibility.isPending}
        onChange={(event) =>
          setVisibility.mutate({ memberId: membershipId, isPublic: event.target.checked })
        }
      />
      <button
        type="button"
        disabled={leave.isPending}
        onClick={() => {
          if (
            window.confirm(`Leave ${organization.name}? You will need a new invitation to return.`)
          ) {
            leave.mutate(undefined, { onSuccess: () => void navigate("/organizations") });
          }
        }}
      >
        Leave organization
      </button>
    </section>
  );
}

function Details({ organization }: { organization: OrganizationDetail }) {
  const update = useUpdateOrganization(organization.id);
  const [editing, setEditing] = useState(false);
  const facts = [organization.industry, formatLocation(organization)].filter(Boolean);

  if (editing) {
    return (
      <section className="card" aria-labelledby="edit-heading">
        <h2 id="edit-heading">Edit details</h2>
        <OrganizationForm
          initial={organization}
          submitLabel="Save"
          onCancel={() => setEditing(false)}
          onSubmit={async (values) => {
            await update.mutateAsync(values);
            setEditing(false);
          }}
        />
      </section>
    );
  }
  return (
    <>
      <div className="page-heading">
        <h1>
          {organization.name}
          {organization.verification_status === "VERIFIED" && (
            <span className="badge badge-ok"> Verified</span>
          )}
        </h1>
        {organization.viewer.can_manage && (
          <button type="button" onClick={() => setEditing(true)}>
            Edit details
          </button>
        )}
      </div>
      {organization.status === "SUSPENDED" && (
        <Notice kind="error">This organization is suspended and hidden from other people.</Notice>
      )}
      {facts.length > 0 && <p className="muted">{facts.join(" · ")}</p>}
      {organization.website && (
        <p>
          {/* User-supplied link: no referrer, and no access to this window. */}
          <a href={organization.website} target="_blank" rel="noopener noreferrer nofollow">
            {organization.website}
          </a>
        </p>
      )}
      {organization.description && <p className="prose">{organization.description}</p>}
    </>
  );
}

export function OrganizationPage() {
  const { organizationId = "" } = useParams();
  const status = useSessionStatus();
  const organization = useOrganization(organizationId);

  if (organization.isPending) {
    return <Splash />;
  }
  if (organization.isError) {
    const notFound = organization.error instanceof ApiError && organization.error.status === 404;
    return (
      <>
        <h1>{notFound ? "Organization not found" : "Something went wrong"}</h1>
        <p className="muted">
          {notFound
            ? "This organization does not exist or is not available."
            : errorMessage(organization.error)}
        </p>
        {!notFound && (
          <button type="button" onClick={() => void organization.refetch()}>
            Try again
          </button>
        )}
        <p className="form-links">
          <Link to="/organizations">Back to organizations</Link>
        </p>
      </>
    );
  }

  const data = organization.data;
  return (
    <>
      <Details organization={data} />

      <section className="card" aria-labelledby="members-heading">
        <h2 id="members-heading">Members ({data.member_count})</h2>
        {!data.viewer.role && (
          <p className="muted">Only members who chose to be listed publicly are shown.</p>
        )}
        <MemberList organization={data} signedIn={status === "authenticated"} />
      </section>

      {data.viewer.can_manage && (
        <section className="card" aria-labelledby="invite-heading">
          <h2 id="invite-heading">Invite people</h2>
          <InvitationPanel organization={data} />
        </section>
      )}

      <YourMembership organization={data} />
      {/* Members who post for the organization see how its postings do; owners also its log. */}
      {data.viewer.role && data.viewer.role !== "MEMBER" && (
        <p className="report-line">
          <Link to={`/organizations/${data.id}/insights`}>Insights</Link>
          {data.viewer.role === "OWNER" && (
            <>
              {" · "}
              <Link to={`/organizations/${data.id}/audit`}>Activity log</Link>
            </>
          )}
        </p>
      )}
      <ReportButton targetType="ORGANIZATION" targetId={data.id} what="organization" />
    </>
  );
}
