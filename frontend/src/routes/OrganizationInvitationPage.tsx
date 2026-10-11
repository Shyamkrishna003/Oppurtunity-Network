import { Link, useNavigate, useParams } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useMe } from "../features/auth/api";
import { useReceivedInvitation, useRespondToInvitation } from "../features/organizations/api";
import { ROLE_LABELS, type InvitationStatus } from "../features/organizations/types";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

const CLOSED: Record<Exclude<InvitationStatus, "PENDING">, string> = {
  ACCEPTED: "This invitation has already been accepted.",
  DECLINED: "This invitation was declined.",
  REVOKED: "This invitation was withdrawn by the organization.",
  EXPIRED: "This invitation has expired. Ask the organization to send a new one.",
};

export function OrganizationInvitationPage() {
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const me = useMe();
  const invitation = useReceivedInvitation(token);
  const respond = useRespondToInvitation(token);

  if (invitation.isPending) {
    return <Splash />;
  }
  if (invitation.isError) {
    const status = invitation.error instanceof ApiError ? invitation.error.status : 0;
    const code = invitation.error instanceof ApiError ? invitation.error.code : "";
    return (
      <>
        <h1>Invitation</h1>
        <Notice kind="error">
          {status === 404
            ? "This invitation link is not valid. Open the link from your email again."
            : code === "email_not_verified"
              ? "Confirm your email address before opening an invitation. Use the link we emailed you, or request a new one from the banner above."
              : errorMessage(invitation.error)}
        </Notice>
        {code === "invitation_email_mismatch" && me.data && (
          <p className="muted">You are signed in as {me.data.email}.</p>
        )}
        <p className="form-links">
          <Link to="/">Back to home</Link>
        </p>
      </>
    );
  }

  const { organization, role, status, invited_by: invitedBy } = invitation.data;
  const unverified = me.data ? !me.data.email_verified : false;

  if (respond.isSuccess && respond.variables === "decline") {
    return (
      <>
        <h1>Invitation declined</h1>
        <p>You declined the invitation to join {organization.name}.</p>
        <Link to="/">Back to home</Link>
      </>
    );
  }

  return (
    <>
      <h1>Join {organization.name}?</h1>
      <p>
        {invitedBy ?? "Someone"} invited you to join <strong>{organization.name}</strong> as{" "}
        {role === "MEMBER" ? "a" : "an"} <strong>{ROLE_LABELS[role].toLowerCase()}</strong>.
      </p>
      {respond.isError && <Notice kind="error">{errorMessage(respond.error)}</Notice>}
      {status !== "PENDING" ? (
        <>
          <Notice kind="error">{CLOSED[status]}</Notice>
          <Link to={`/organizations/${organization.id}`}>View {organization.name}</Link>
        </>
      ) : (
        <>
          {unverified && (
            <Notice kind="error">
              Confirm your email address before accepting. Use the link we emailed you, or request a
              new one from the banner above.
            </Notice>
          )}
          <div className="button-row">
            <button
              type="button"
              className="primary"
              disabled={respond.isPending || unverified}
              onClick={() =>
                respond.mutate("accept", {
                  onSuccess: () => void navigate(`/organizations/${organization.id}`),
                })
              }
            >
              {respond.isPending && respond.variables === "accept" ? "Joining…" : "Accept"}
            </button>
            <button
              type="button"
              disabled={respond.isPending}
              onClick={() => respond.mutate("decline")}
            >
              Decline
            </button>
          </div>
        </>
      )}
    </>
  );
}
