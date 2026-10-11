import { Link } from "react-router";

import { Avatar } from "../../components/Avatar";
import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { useChangeCommunityRole, useCommunityMembers, useMemberAction } from "./api";
import {
  ROLE_LABELS,
  ROLE_ORDER,
  type CommunityDetail,
  type CommunityMember,
  type CommunityRole,
  type ListableStatus,
  type MemberAction,
} from "./types";

const EMPTY: Record<ListableStatus, string> = {
  ACTIVE: "No members yet.",
  PENDING: "No requests waiting.",
  INVITED: "No unanswered invitations.",
  BANNED: "Nobody is banned.",
};

interface ActionSpec {
  action: MemberAction;
  label: string;
  /** Asked before acting; omitted for actions that are easy to undo. */
  confirm?: (name: string) => string;
}

const REMOVE: ActionSpec = {
  action: "remove",
  label: "Remove",
  confirm: (name) => `Remove ${name} from this community?`,
};
const BAN: ActionSpec = {
  action: "ban",
  label: "Ban",
  confirm: (name) => `Ban ${name}? They will not be able to rejoin until the ban is lifted.`,
};

/** The actions the viewer may take on one person, mirroring the server's rules. */
function actionsFor(community: CommunityDetail, member: CommunityMember): ActionSpec[] {
  const { viewer } = community;
  if (member.id === viewer.membership_id) {
    return [];
  }
  switch (member.status) {
    case "PENDING":
      return [
        ...(viewer.can_review_requests ? [{ action: "approve", label: "Approve" } as const] : []),
        ...(viewer.can_manage ? [{ action: "reject", label: "Reject" } as const] : []),
      ];
    case "INVITED":
      return viewer.can_manage ? [{ action: "remove", label: "Withdraw invitation" }] : [];
    case "BANNED":
      return viewer.can_manage ? [{ action: "unban", label: "Lift ban" }] : [];
    case "ACTIVE":
      // You may act on someone whose role you could have assigned.
      return viewer.assignable_roles.includes(member.role) ? [REMOVE, BAN] : [];
    default:
      return [];
  }
}

function PersonRow({ community, member }: { community: CommunityDetail; member: CommunityMember }) {
  const { viewer } = community;
  const act = useMemberAction(community.id);
  const changeRole = useChangeCommunityRole(community.id);
  const busy = act.isPending || changeRole.isPending;
  const failure = act.error ?? changeRole.error;
  const name = member.user.display_name;
  const isSelf = member.id === viewer.membership_id;
  const actions = actionsFor(community, member);
  const canChangeRole =
    member.status === "ACTIVE" && !isSelf && viewer.assignable_roles.includes(member.role);

  return (
    <li>
      <div className="entry">
        <span className="person">
          <Avatar name={name} url={member.user.avatar_url} size={36} />
          <span>
            <Link to={`/users/${member.user.id}`}>{name}</Link>
            {isSelf && " (you)"}
            {member.user.headline && <span className="muted"> · {member.user.headline}</span>}
          </span>
        </span>
        <div className="button-row">
          {canChangeRole ? (
            <select
              aria-label={`Role of ${name}`}
              value={member.role}
              disabled={busy}
              onChange={(event) =>
                changeRole.mutate({
                  memberId: member.id,
                  role: event.target.value as CommunityRole,
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
            member.status === "ACTIVE" && <span className="badge">{ROLE_LABELS[member.role]}</span>
          )}
          {actions.map(({ action, label, confirm }) => (
            <button
              key={action}
              type="button"
              disabled={busy}
              onClick={() => {
                if (!confirm || window.confirm(confirm(name))) {
                  act.mutate({ memberId: member.id, action });
                }
              }}
            >
              {label} <span className="visually-hidden">{name}</span>
            </button>
          ))}
        </div>
      </div>
      {failure && <Notice kind="error">{errorMessage(failure)}</Notice>}
    </li>
  );
}

/** People in one membership state. Render only for viewers allowed to list that state. */
export function PeopleList({
  community,
  status,
}: {
  community: CommunityDetail;
  status: ListableStatus;
}) {
  const people = useCommunityMembers(community.id, status);

  if (people.isPending) {
    return (
      <p className="muted" role="status">
        Loading…
      </p>
    );
  }
  if (people.isError) {
    return (
      <Notice kind="error">
        <p>{errorMessage(people.error)}</p>
        <button type="button" onClick={() => void people.refetch()}>
          Try again
        </button>
      </Notice>
    );
  }

  const list = people.data.pages.flatMap((page) => page.results);
  if (list.length === 0) {
    return <p className="muted">{EMPTY[status]}</p>;
  }
  return (
    <>
      <ul className="entry-list">
        {list.map((member) => (
          <PersonRow key={member.id} community={community} member={member} />
        ))}
      </ul>
      {people.hasNextPage && (
        <button
          type="button"
          onClick={() => void people.fetchNextPage()}
          disabled={people.isFetchingNextPage}
        >
          {people.isFetchingNextPage ? "Loading…" : "Show more"}
        </button>
      )}
    </>
  );
}
