import { useState } from "react";

import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { useInviteToCommunity, useMyCommunities } from "./api";

/**
 * Lets an owner or admin invite the person whose profile is open. Renders nothing for
 * anyone who does not run a community.
 */
export function InviteToCommunity({ userId, name }: { userId: string; name: string }) {
  const mine = useMyCommunities();
  const invite = useInviteToCommunity();
  const [communityId, setCommunityId] = useState("");

  const managed = (mine.data ?? []).filter(
    (item) => item.status === "ACTIVE" && (item.role === "OWNER" || item.role === "ADMIN"),
  );
  if (managed.length === 0) {
    return null;
  }
  const invitedTo = managed.find((item) => item.community.id === invite.variables?.communityId);

  return (
    <section className="card" aria-labelledby="invite-community-heading">
      <h2 id="invite-community-heading">Invite to a community</h2>
      {invite.isError && <Notice kind="error">{errorMessage(invite.error)}</Notice>}
      {invite.isSuccess && invitedTo && (
        <Notice kind="ok">
          {name} has been invited to {invitedTo.community.name}.
        </Notice>
      )}
      <form
        className="search-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (communityId) {
            invite.mutate({ communityId, userId });
          }
        }}
      >
        <select
          aria-label="Community"
          value={communityId}
          onChange={(event) => setCommunityId(event.target.value)}
        >
          <option value="">Choose a community…</option>
          {managed.map(({ community }) => (
            <option key={community.id} value={community.id}>
              {community.name}
            </option>
          ))}
        </select>
        <button type="submit" disabled={!communityId || invite.isPending}>
          {invite.isPending ? "Inviting…" : "Invite"}
        </button>
      </form>
    </section>
  );
}
