import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { SelectField, TextField } from "../../components/Field";
import { Notice } from "../../components/Notice";
import { applyApiError, errorMessage } from "../../services/formErrors";
import { useInvitations, useInvite, useRevokeInvitation } from "./api";
import { ROLE_LABELS, ROLE_ORDER, type OrganizationDetail, type OrganizationRole } from "./types";

const schema = z.object({
  email: z.string().trim().min(1, "Enter an email address.").email("Enter a valid email address."),
  role: z.enum(["OWNER", "ADMIN", "RECRUITER", "MEMBER"]),
});
type Values = z.infer<typeof schema>;

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

function InviteForm({ organization }: { organization: OrganizationDetail }) {
  const invite = useInvite(organization.id);
  const roles = ROLE_ORDER.filter((role) => organization.viewer.assignable_roles.includes(role));
  const [formError, setFormError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    // The least privileged role is the safe default.
    defaultValues: { email: "", role: roles.at(-1) as OrganizationRole },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    setSentTo(null);
    try {
      const invitation = await invite.mutateAsync(values);
      setSentTo(invitation.email);
      reset({ email: "", role: values.role });
    } catch (error) {
      setFormError(applyApiError(error, setError, ["email", "role"]));
    }
  });

  return (
    <form onSubmit={(event) => void onSubmit(event)} noValidate>
      {formError && <Notice kind="error">{formError}</Notice>}
      {sentTo && <Notice kind="ok">Invitation sent to {sentTo}.</Notice>}
      <div className="field-row">
        <TextField
          label="Email address"
          type="email"
          autoComplete="off"
          error={errors.email?.message}
          {...register("email")}
        />
        <SelectField label="Role" error={errors.role?.message} {...register("role")}>
          {roles.map((role) => (
            <option key={role} value={role}>
              {ROLE_LABELS[role]}
            </option>
          ))}
        </SelectField>
      </div>
      <button type="submit" className="primary" disabled={invite.isPending}>
        {invite.isPending ? "Sending…" : "Send invitation"}
      </button>
    </form>
  );
}

function OpenInvitations({ organization }: { organization: OrganizationDetail }) {
  const invitations = useInvitations(organization.id, organization.viewer.can_manage);
  const revoke = useRevokeInvitation(organization.id);

  if (invitations.isPending) {
    return (
      <p className="muted" role="status">
        Loading invitations…
      </p>
    );
  }
  if (invitations.isError) {
    return (
      <Notice kind="error">
        <p>{errorMessage(invitations.error)}</p>
        <button type="button" onClick={() => void invitations.refetch()}>
          Try again
        </button>
      </Notice>
    );
  }

  const list = invitations.data.pages.flatMap((page) => page.results);
  if (list.length === 0) {
    return <p className="muted">No open invitations.</p>;
  }
  return (
    <>
      {revoke.isError && <Notice kind="error">{errorMessage(revoke.error)}</Notice>}
      <ul className="entry-list">
        {list.map((invitation) => (
          <li key={invitation.id} className="entry">
            <div>
              <strong>{invitation.email}</strong>
              <div className="muted">
                {ROLE_LABELS[invitation.role]} · expires{" "}
                {dateFormat.format(new Date(invitation.expires_at))}
                {invitation.invited_by && ` · invited by ${invitation.invited_by}`}
              </div>
            </div>
            {organization.viewer.assignable_roles.includes(invitation.role) && (
              <button
                type="button"
                disabled={revoke.isPending}
                onClick={() => revoke.mutate(invitation.id)}
              >
                Withdraw <span className="visually-hidden">invitation to {invitation.email}</span>
              </button>
            )}
          </li>
        ))}
      </ul>
      {invitations.hasNextPage && (
        <button
          type="button"
          onClick={() => void invitations.fetchNextPage()}
          disabled={invitations.isFetchingNextPage}
        >
          Show more
        </button>
      )}
    </>
  );
}

/** Invite people and manage open invitations. Render only for owners and admins. */
export function InvitationPanel({ organization }: { organization: OrganizationDetail }) {
  return (
    <>
      <p className="muted">
        The person gets an email with a link. They join once they accept it, signed in with an
        account that uses that address.
      </p>
      <InviteForm organization={organization} />
      <h3>Open invitations</h3>
      <OpenInvitations organization={organization} />
    </>
  );
}
