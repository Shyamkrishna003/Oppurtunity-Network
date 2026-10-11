import { Link } from "react-router";

import { Avatar } from "../../components/Avatar";
import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { useChangeRole, useMembers, useRemoveMember, useTransferOwnership } from "./api";
import {
  ROLE_LABELS,
  ROLE_ORDER,
  type Member,
  type OrganizationDetail,
  type OrganizationRole,
} from "./types";

interface MemberRowProps {
  organization: OrganizationDetail;
  member: Member;
  signedIn: boolean;
}

function MemberRow({ organization, member, signedIn }: MemberRowProps) {
  const { viewer } = organization;
  const changeRole = useChangeRole(organization.id);
  const remove = useRemoveMember(organization.id);
  const transfer = useTransferOwnership(organization.id);

  const isSelf = member.id === viewer.membership_id;
  // Mirrors the server's rule: you may act on someone whose role you could have assigned.
  const canAct = !isSelf && viewer.assignable_roles.includes(member.role);
  const canTransfer = !isSelf && viewer.role === "OWNER";
  const busy = changeRole.isPending || remove.isPending || transfer.isPending;
  const failure = changeRole.error ?? remove.error ?? transfer.error;
  const name = member.user.display_name;

  return (
    <li>
      <div className="entry">
        <span className="person">
          <Avatar name={name} url={member.user.avatar_url} size={36} />
          <span>
            {signedIn ? <Link to={`/users/${member.user.id}`}>{name}</Link> : name}
            {isSelf && " (you)"}
            {member.user.headline && <span className="muted"> · {member.user.headline}</span>}
          </span>
        </span>
        <div className="button-row">
          {canAct ? (
            <select
              aria-label={`Role of ${name}`}
              value={member.role}
              disabled={busy}
              onChange={(event) =>
                changeRole.mutate({
                  memberId: member.id,
                  role: event.target.value as OrganizationRole,
                })
              }
            >
              {ROLE_ORDER.filter((role) => viewer.assignable_roles.includes(role)).map((role) => (
                <option key={role} value={role}>
                  {ROLE_LABELS[role]}
                </option>
              ))}
            </select>
          ) : (
            <span className="badge">{ROLE_LABELS[member.role]}</span>
          )}
          {canTransfer && (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (
                  window.confirm(
                    `Make ${name} the owner? You will become an admin and cannot undo this yourself.`,
                  )
                ) {
                  transfer.mutate(member.id);
                }
              }}
            >
              Transfer ownership <span className="visually-hidden">to {name}</span>
            </button>
          )}
          {canAct && (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (window.confirm(`Remove ${name} from ${organization.name}?`)) {
                  remove.mutate(member.id);
                }
              }}
            >
              Remove <span className="visually-hidden">{name}</span>
            </button>
          )}
        </div>
      </div>
      {failure && <Notice kind="error">{errorMessage(failure)}</Notice>}
    </li>
  );
}

export function MemberList({
  organization,
  signedIn,
}: {
  organization: OrganizationDetail;
  signedIn: boolean;
}) {
  const members = useMembers(organization.id);

  if (members.isPending) {
    return (
      <p className="muted" role="status">
        Loading members…
      </p>
    );
  }
  if (members.isError) {
    return (
      <Notice kind="error">
        <p>{errorMessage(members.error)}</p>
        <button type="button" onClick={() => void members.refetch()}>
          Try again
        </button>
      </Notice>
    );
  }

  const list = members.data.pages.flatMap((page) => page.results);
  if (list.length === 0) {
    return <p className="muted">No members are listed publicly.</p>;
  }
  return (
    <>
      <ul className="entry-list">
        {list.map((member) => (
          <MemberRow
            key={member.id}
            organization={organization}
            member={member}
            signedIn={signedIn}
          />
        ))}
      </ul>
      {members.hasNextPage && (
        <button
          type="button"
          onClick={() => void members.fetchNextPage()}
          disabled={members.isFetchingNextPage}
        >
          {members.isFetchingNextPage ? "Loading…" : "Show more"}
        </button>
      )}
    </>
  );
}
