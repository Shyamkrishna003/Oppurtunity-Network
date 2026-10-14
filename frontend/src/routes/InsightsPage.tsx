import type { ReactNode } from "react";
import { Link, useParams } from "react-router";

import { Figures } from "../components/Figures";
import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useCommunityNumbers, useOrganizationNumbers } from "../features/insights/api";
import { FunnelChart } from "../features/opportunities/FunnelChart";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

const number = new Intl.NumberFormat();

/** The frame both pages share: where to go back to, the heading, and what to say while
 *  loading, when refused, or when it failed. */
function Frame({
  back,
  backLabel,
  forWhom,
  query,
  children,
}: {
  back: string;
  backLabel: string;
  forWhom: string;
  query: { isPending: boolean; error: unknown; refetch: () => unknown };
  children: ReactNode;
}) {
  const refused =
    query.error instanceof ApiError && (query.error.status === 403 || query.error.status === 404);
  return (
    <>
      <p>
        <Link to={back}>{backLabel}</Link>
      </p>
      <h1>Insights</h1>
      {query.isPending ? (
        <Splash />
      ) : refused ? (
        <p className="muted">This page is for {forWhom}.</p>
      ) : query.error ? (
        <Notice kind="error">
          <p>{errorMessage(query.error)}</p>
          <button type="button" onClick={() => void query.refetch()}>
            Try again
          </button>
        </Notice>
      ) : (
        children
      )}
    </>
  );
}

/** How everything an organization posted is doing. */
export function OrganizationInsightsPage() {
  const { organizationId = "" } = useParams();
  const query = useOrganizationNumbers(organizationId);
  const data = query.data;
  return (
    <Frame
      back={`/organizations/${organizationId}`}
      backLabel="Back to the organization"
      forWhom="the people who post for the organization"
      query={query}
    >
      {data && (
        <>
          <Figures
            title="What it has posted"
            figures={[
              ["Open now", data.opportunities.published],
              ["Drafts", data.opportunities.drafts],
              ["Finished", data.opportunities.finished],
            ]}
          />
          {data.funnels.length === 0 ? (
            <p className="muted">
              Nothing to show yet. Once the organization publishes something, how far people get
              with it appears here.
            </p>
          ) : (
            <section className="card" aria-labelledby="funnels-heading">
              <h2 id="funnels-heading">How far people get</h2>
              <p className="muted">
                Across everything the organization posted. Each step counts everyone who reached it,
                whatever happened afterwards.
              </p>
              {data.funnels.map((funnel) => (
                <FunnelChart key={funnel.name} funnel={funnel} />
              ))}
            </section>
          )}
          {data.top.length > 0 && (
            <section className="card" aria-labelledby="top-heading">
              <h2 id="top-heading">Drawing the most now</h2>
              <ol className="entry-list">
                {data.top.map((row) => (
                  <li key={row.id} className="entry">
                    <Link to={`/opportunities/${row.id}`}>
                      <strong>{row.title}</strong>
                    </Link>
                    <span className="muted">
                      {number.format(row.views)} opened it ·{" "}
                      {row.type === "EVENT"
                        ? `${number.format(row.registrations)} places held`
                        : `${number.format(row.applications)} applied`}
                    </span>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </>
      )}
    </Frame>
  );
}

/** How a community is doing: its members, what it shows, and reports waiting. */
export function CommunityInsightsPage() {
  const { communityId = "" } = useParams();
  const query = useCommunityNumbers(communityId);
  const data = query.data;
  return (
    <Frame
      back={`/communities/${communityId}`}
      backLabel="Back to the community"
      forWhom="the community's owners and admins"
      query={query}
    >
      {data && (
        <>
          <Figures
            title="Members"
            figures={[
              ["Members", data.members.active],
              ["Asked to join", data.members.asked_to_join],
              ["Invited", data.members.invited],
            ]}
          />
          <Figures
            title="Opportunities"
            figures={[
              ["Shown now", data.sharing.shown],
              ["Jobs", data.sharing.jobs_shown],
              ["Events", data.sharing.events_shown],
              ["Featured", data.sharing.featured],
              ["Waiting for review", data.sharing.waiting],
              ["Ever offered", data.sharing.offered],
              ["Declined", data.sharing.declined],
              ["Removed", data.sharing.removed],
            ]}
          />
          <Figures
            title="Reports from members"
            figures={[
              ["Waiting", data.reports.waiting],
              ["Decided", data.reports.decided],
            ]}
          />
          <p className="muted">
            Applications and registrations are not shown here: an opportunity is usually shared in
            several places, and nothing records which of them led someone to act.
          </p>
        </>
      )}
    </Frame>
  );
}
