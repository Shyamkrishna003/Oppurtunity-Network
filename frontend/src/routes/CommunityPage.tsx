import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useMe, useSessionStatus } from "../features/auth/api";
import {
  useCommunity,
  useJoinCommunity,
  useLeaveCommunity,
  useUpdateCommunity,
} from "../features/communities/api";
import { CommunityForm } from "../features/communities/CommunityForm";
import { PeopleList } from "../features/communities/PeopleList";
import {
  CommunityOpportunityList,
  ReviewQueue,
} from "../features/opportunities/CommunityOpportunities";
import { RulesEditor } from "../features/communities/RulesEditor";
import { ReportButton } from "../features/moderation/ReportButton";
import {
  JOIN_POLICY_LABELS,
  ROLE_LABELS,
  type CommunityDetail,
  type JoinAction,
} from "../features/communities/types";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

const JOIN_LABELS: Record<JoinAction, string> = {
  join: "Join community",
  request: "Ask to join",
  accept: "Accept invitation",
};

/** The viewer's own standing in the community and the one thing they can do about it. */
function Membership({ community }: { community: CommunityDetail }) {
  const { viewer } = community;
  const status = useSessionStatus();
  const me = useMe();
  const navigate = useNavigate();
  const join = useJoinCommunity(community.id);
  const leave = useLeaveCommunity(community.id);
  const busy = join.isPending || leave.isPending;
  const failure = join.error ?? leave.error;
  const unverified = me.data ? !me.data.email_verified : false;

  if (status !== "authenticated") {
    return (
      <p>
        <Link to={`/login?next=${encodeURIComponent(`/communities/${community.id}`)}`}>
          Sign in
        </Link>{" "}
        to join this community.
      </p>
    );
  }

  const leaveButton = (label: string, question: string, leavesPage: boolean) => (
    <button
      type="button"
      disabled={busy}
      onClick={() => {
        if (window.confirm(question)) {
          leave.mutate(undefined, {
            // A private community disappears for someone who is no longer in it.
            onSuccess: () => (leavesPage ? void navigate("/communities") : undefined),
          });
        }
      }}
    >
      {label}
    </button>
  );
  const isPrivate = community.visibility === "PRIVATE";

  return (
    <>
      {failure && <Notice kind="error">{errorMessage(failure)}</Notice>}
      {viewer.status === "ACTIVE" && viewer.role && (
        <p>
          You are {viewer.role === "MEMBER" || viewer.role === "MODERATOR" ? "a" : "an"}{" "}
          <strong>{ROLE_LABELS[viewer.role].toLowerCase()}</strong> of this community.
        </p>
      )}
      {viewer.status === "PENDING" && (
        <Notice kind="ok">Your request to join is waiting for an admin to review it.</Notice>
      )}
      {viewer.status === "INVITED" && (
        <Notice kind="ok">You have been invited to join this community.</Notice>
      )}
      {viewer.status === "BANNED" && <Notice kind="error">You cannot join this community.</Notice>}
      {viewer.status === null && !viewer.join_action && (
        <p className="muted">This community can only be joined by invitation.</p>
      )}
      {viewer.join_action && unverified && (
        <Notice kind="error">Confirm your email address before joining a community.</Notice>
      )}
      <div className="button-row">
        {viewer.join_action && (
          <button
            type="button"
            className="primary"
            disabled={busy || unverified}
            onClick={() => join.mutate()}
          >
            {join.isPending ? "Working…" : JOIN_LABELS[viewer.join_action]}
          </button>
        )}
        {viewer.status === "ACTIVE" &&
          leaveButton("Leave community", `Leave ${community.name}?`, isPrivate)}
        {viewer.status === "INVITED" &&
          leaveButton("Decline", `Decline the invitation to ${community.name}?`, isPrivate)}
        {viewer.status === "PENDING" &&
          leaveButton("Withdraw request", "Withdraw your request to join?", false)}
      </div>
    </>
  );
}

function Details({ community }: { community: CommunityDetail }) {
  const update = useUpdateCommunity(community.id);
  const [editing, setEditing] = useState(false);
  const facts = [
    community.category,
    `${community.member_count} ${community.member_count === 1 ? "member" : "members"}`,
    JOIN_POLICY_LABELS[community.join_policy],
    community.visibility === "PRIVATE" && "Private",
  ].filter(Boolean);

  if (editing) {
    return (
      <section className="card" aria-labelledby="edit-heading">
        <h2 id="edit-heading">Edit community</h2>
        <CommunityForm
          initial={community}
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
          {community.name}
          {community.is_verified && <span className="badge badge-ok"> Verified</span>}
        </h1>
        {community.viewer.can_manage && (
          <button type="button" onClick={() => setEditing(true)}>
            Edit community
          </button>
        )}
      </div>
      {community.status === "SUSPENDED" && (
        <Notice kind="error">This community is suspended and hidden from other people.</Notice>
      )}
      <p className="muted">{facts.join(" · ")}</p>
      {community.description && <p className="prose">{community.description}</p>}
    </>
  );
}

function Rules({ community }: { community: CommunityDetail }) {
  const [editing, setEditing] = useState(false);
  if (community.rules.length === 0 && !community.viewer.can_manage) {
    return null;
  }
  return (
    <section className="card" aria-labelledby="rules-heading">
      <div className="page-heading">
        <h2 id="rules-heading">Rules</h2>
        {community.viewer.can_manage && !editing && (
          <button type="button" onClick={() => setEditing(true)}>
            Edit rules
          </button>
        )}
      </div>
      {editing ? (
        <RulesEditor community={community} onDone={() => setEditing(false)} />
      ) : community.rules.length === 0 ? (
        <p className="muted">No rules yet.</p>
      ) : (
        <ol className="rules">
          {community.rules.map((rule, index) => (
            <li key={index}>
              <strong>{rule.title}</strong>
              {rule.body && <p className="prose">{rule.body}</p>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function CommunityPage() {
  const { communityId = "" } = useParams();
  const community = useCommunity(communityId);

  if (community.isPending) {
    return <Splash />;
  }
  if (community.isError) {
    const notFound = community.error instanceof ApiError && community.error.status === 404;
    return (
      <>
        <h1>{notFound ? "Community not found" : "Something went wrong"}</h1>
        <p className="muted">
          {notFound
            ? "This community does not exist, or it is private and you are not a member."
            : errorMessage(community.error)}
        </p>
        {!notFound && (
          <button type="button" onClick={() => void community.refetch()}>
            Try again
          </button>
        )}
        <p className="form-links">
          <Link to="/communities">Back to communities</Link>
        </p>
      </>
    );
  }

  const data = community.data;
  const { viewer } = data;
  const isMember = viewer.status === "ACTIVE";
  return (
    <>
      <Details community={data} />

      <section className="card" aria-labelledby="membership-heading">
        <h2 id="membership-heading">Your membership</h2>
        <Membership community={data} />
      </section>

      <Rules community={data} />

      {viewer.can_review_requests && (
        <section className="card" aria-labelledby="review-heading">
          <h2 id="review-heading">Opportunities waiting for review</h2>
          <ReviewQueue communityId={data.id} />
        </section>
      )}

      <section className="card" aria-labelledby="opportunities-heading">
        <h2 id="opportunities-heading">Opportunities</h2>
        <CommunityOpportunityList communityId={data.id} canReview={viewer.can_review_requests} />
      </section>

      {viewer.can_review_requests && (
        <section className="card" aria-labelledby="running-heading">
          <h2 id="running-heading">Running the community</h2>
          <p className="button-row">
            <Link to={`/communities/${data.id}/reports`}>Reports from members</Link>
            {viewer.can_manage && <Link to={`/communities/${data.id}/insights`}>Insights</Link>}
            {viewer.role === "OWNER" && (
              <Link to={`/communities/${data.id}/audit`}>Activity log</Link>
            )}
          </p>
        </section>
      )}

      {viewer.can_review_requests && (
        <section className="card" aria-labelledby="requests-heading">
          <h2 id="requests-heading">Requests to join</h2>
          <PeopleList community={data} status="PENDING" />
        </section>
      )}

      {isMember && (
        <section className="card" aria-labelledby="members-heading">
          <h2 id="members-heading">Members ({data.member_count})</h2>
          <PeopleList community={data} status="ACTIVE" />
        </section>
      )}

      {viewer.can_manage && (
        <>
          <section className="card" aria-labelledby="invited-heading">
            <h2 id="invited-heading">Invited</h2>
            <p className="muted">
              To invite someone, open their profile and choose “Invite to a community”.
            </p>
            <PeopleList community={data} status="INVITED" />
          </section>
          <section className="card" aria-labelledby="banned-heading">
            <h2 id="banned-heading">Banned</h2>
            <PeopleList community={data} status="BANNED" />
          </section>
        </>
      )}

      <ReportButton targetType="COMMUNITY" targetId={data.id} what="community" />
    </>
  );
}
