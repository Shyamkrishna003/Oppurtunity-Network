import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CommunityDetail, CommunityViewer } from "../features/communities/types";
import type {
  Opportunity,
  OpportunityDetail,
  Share,
  ShareOption,
} from "../features/opportunities/types";
import { makeSession } from "../test/fixtures";
import { apiError, json, mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const JOB = "/api/v1/opportunities/opp-1/";
const COMMUNITY = "/api/v1/communities/com-1/";
const page = <T,>(results: T[]) => json({ results, next: null, previous: null });
const ref = (id: string, name: string) => ({ id, name, slug: id });

function opportunity(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: "opp-1",
    type: "JOB",
    title: "Backend Engineer",
    description: "Build and run our Django services.",
    status: "PUBLISHED",
    visibility: "PUBLIC",
    work_mode: "REMOTE",
    country_code: "",
    region: "",
    city: "",
    deadline: null,
    published_at: "2026-10-01T00:00:00Z",
    closed_at: null,
    close_reason: "",
    created_at: "2026-09-30T00:00:00Z",
    organization: null,
    posted_by: { id: "u-1", display_name: "Ada Lovelace", headline: "", avatar_url: null },
    skills: [{ id: "s-py", name: "Python", slug: "python" }],
    job: {
      department: "",
      employment_type: "FULL_TIME",
      experience_level: "MID",
      salary_min: null,
      salary_max: null,
      salary_currency: "",
      salary_period: "",
      application_method: "INTERNAL",
      external_url: "",
      openings: 1,
    },
    ...overrides,
  };
}

function managedJob(overrides: Partial<OpportunityDetail> = {}): OpportunityDetail {
  return {
    ...opportunity(),
    moderation_status: "VISIBLE",
    communities: [],
    viewer: { can_manage: true, editable_fields: ["deadline", "description"], is_saved: false },
    ...overrides,
  };
}

function share(id: string, name: string, overrides: Partial<Share> = {}): Share {
  return {
    id: `share-${id}`,
    community: ref(id, name),
    status: "PENDING",
    rejection_reason: "",
    is_featured: false,
    created_at: "2026-10-02T00:00:00Z",
    ...overrides,
  };
}

const option = (id: string, name: string, outcome: ShareOption["outcome"]): ShareOption => ({
  community: ref(id, name),
  current: null,
  outcome,
});

beforeEach(() => vi.spyOn(window, "confirm").mockReturnValue(true));
afterEach(() => vi.unstubAllGlobals());

describe("sharing a job with communities", () => {
  const OPTIONS = [
    option("com-1", "Kochi Developers", "PENDING"),
    option("com-2", "React India", "APPROVED"),
    option("com-3", "Admins Only Club", null),
  ];

  it("explains what sharing would do in each community and shares the chosen ones", async () => {
    const api = mockApi({
      [`GET ${JOB}`]: () => json(managedJob()),
      [`GET ${JOB}communities/`]: () => json([]),
      [`GET ${JOB}communities/options/`]: () => json(OPTIONS),
      [`POST ${JOB}communities/`]: () => json([share("com-1", "Kochi Developers")]),
    });
    renderApp("/opportunities/opp-1", makeSession());
    const user = userEvent.setup();

    const panel = await screen.findByRole("region", { name: "Share with communities" });
    const kochi = await within(panel).findByLabelText("Kochi Developers");
    expect(within(panel).getByText("a moderator of the community reviews it first.")).toBeVisible();
    expect(within(panel).getByText("it will be shown to members straight away.")).toBeVisible();
    expect(within(panel).getByLabelText("Admins Only Club")).toBeDisabled();
    expect(within(panel).getByRole("button", { name: "Share" })).toBeDisabled();

    await user.click(kochi);
    await user.click(within(panel).getByLabelText("React India"));
    await user.click(within(panel).getByRole("button", { name: "Share" }));

    await waitFor(() =>
      expect(api.last(`POST ${JOB}communities/`)?.body).toEqual({
        community_ids: ["com-1", "com-2"],
      }),
    );
  });

  it("shows each community's decision and lets the manager withdraw", async () => {
    const api = mockApi({
      [`GET ${JOB}`]: () => json(managedJob()),
      [`GET ${JOB}communities/`]: () =>
        json([
          share("com-1", "Kochi Developers", { status: "APPROVED", is_featured: true }),
          share("com-2", "React India", { status: "REJECTED", rejection_reason: "Off topic." }),
          share("com-4", "Strict Group", { status: "REMOVED" }),
        ]),
      [`GET ${JOB}communities/options/`]: () =>
        json([{ ...option("com-2", "React India", "PENDING"), current: "REJECTED" }]),
      [`DELETE ${JOB}communities/com-1/`]: () => new Response(null, { status: 204 }),
    });
    renderApp("/opportunities/opp-1", makeSession());
    const user = userEvent.setup();

    const list = await screen.findByRole("list", { name: "Communities this is shared with" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Kochi Developers");
    expect(rows[0]).toHaveTextContent("Shown");
    expect(rows[0]).toHaveTextContent("Featured");
    expect(rows[1]).toHaveTextContent("Reason: Off topic.");
    expect(rows[2]).toHaveTextContent("Removed by the community");
    // A share the community removed cannot be withdrawn; a rejected one can be offered again.
    expect(within(rows[2]!).queryByRole("button")).toBeNull();
    expect(await screen.findByText(/Offer it again/)).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Withdraw from Kochi Developers" }));
    await waitFor(() => expect(api.count(`DELETE ${JOB}communities/com-1/`)).toBe(1));
  });

  it("names the communities that refused when nothing could be shared", async () => {
    mockApi({
      [`GET ${JOB}`]: () => json(managedJob()),
      [`GET ${JOB}communities/`]: () => json([]),
      [`GET ${JOB}communities/options/`]: () => json(OPTIONS),
      [`POST ${JOB}communities/`]: () =>
        apiError(422, "cannot_share", "This opportunity cannot be shared.", {
          "com-1": ["You are not a member of this community."],
        }),
    });
    renderApp("/opportunities/opp-1", makeSession());
    const user = userEvent.setup();

    await user.click(await screen.findByLabelText("Kochi Developers"));
    await user.click(screen.getByRole("button", { name: "Share" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nothing was shared");
    expect(alert).toHaveTextContent("Kochi Developers: You are not a member of this community.");
  });

  it("is offered only to managers of a published job", async () => {
    const api = mockApi({
      [`GET ${JOB}`]: () =>
        json(
          managedJob({
            status: "DRAFT",
            published_at: null,
            viewer: { can_manage: true, editable_fields: null, is_saved: false },
          }),
        ),
    });
    renderApp("/opportunities/opp-1", makeSession());

    expect(await screen.findByRole("heading", { name: "Manage" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Share with communities" })).toBeNull();
    expect(api.count(`GET ${JOB}communities/options/`)).toBe(0);
  });

  it("tells any reader which communities show the job", async () => {
    mockApi({
      [`GET ${JOB}`]: () =>
        json(
          managedJob({
            communities: [ref("com-1", "Kochi Developers"), ref("com-2", "React India")],
            viewer: { can_manage: false, editable_fields: [], is_saved: false },
          }),
        ),
    });
    renderApp("/opportunities/opp-1");

    expect(await screen.findByRole("link", { name: "Kochi Developers" })).toHaveAttribute(
      "href",
      "/communities/com-1",
    );
    expect(screen.getByRole("link", { name: "React India" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Share with communities" })).toBeNull();
  });
});

describe("opportunities in a community", () => {
  const OUTSIDER: CommunityViewer = {
    membership_id: null,
    status: null,
    role: null,
    join_action: "join",
    can_manage: false,
    can_review_requests: false,
    assignable_roles: [],
  };
  const MODERATOR: CommunityViewer = {
    membership_id: "m-me",
    status: "ACTIVE",
    role: "MODERATOR",
    join_action: null,
    can_manage: false,
    can_review_requests: true,
    assignable_roles: [],
  };

  function community(viewer: CommunityViewer): CommunityDetail {
    return {
      id: "com-1",
      name: "Kochi Developers",
      slug: "kochi-developers",
      description: "",
      category: "",
      join_policy: "OPEN",
      posting_policy: "MEMBERS_WITH_APPROVAL",
      visibility: "PUBLIC",
      is_verified: false,
      status: "ACTIVE",
      member_count: 3,
      created_at: "2026-10-01T00:00:00Z",
      rules: [],
      viewer,
    };
  }

  const pinned = {
    share_id: "share-2",
    is_featured: true,
    opportunity: opportunity({ id: "opp-2", title: "Frontend Engineer" }),
  };
  const plain = { share_id: "share-1", is_featured: false, opportunity: opportunity() };

  function routes(viewer: CommunityViewer) {
    return {
      [`GET ${COMMUNITY}`]: () => json(community(viewer)),
      [`GET ${COMMUNITY}members/`]: () => page([]),
      [`GET ${COMMUNITY}opportunities/`]: ({ url }: { url: URL }) =>
        page(url.searchParams.get("featured") === "true" ? [pinned] : [plain, pinned]),
      [`GET ${COMMUNITY}submissions/`]: () =>
        page([
          {
            id: "share-9",
            status: "PENDING",
            is_featured: false,
            rejection_reason: "",
            created_at: "2026-10-03T00:00:00Z",
            reviewed_at: null,
            submitted_by: { id: "u-2", display_name: "Mia Member", headline: "", avatar_url: null },
            opportunity: opportunity({ id: "opp-9", title: "Data Analyst" }),
          },
        ]),
    };
  }

  it("shows a visitor the list, pinned first, with no controls", async () => {
    const api = mockApi(routes(OUTSIDER));
    renderApp("/communities/com-1");

    const section = await screen.findByRole("region", { name: "Opportunities" });
    await within(section).findByRole("link", { name: "Backend Engineer" });
    const titles = within(section)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(titles).toEqual(["Frontend Engineer", "Backend Engineer"]); // each shown once
    expect(within(section).getByText("Featured")).toBeVisible();
    expect(within(section).getAllByText("Full-time · Mid level · Remote")).toHaveLength(2);
    expect(within(section).queryByRole("button")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Opportunities waiting for review" })).toBeNull();
    expect(api.count(`GET ${COMMUNITY}submissions/`)).toBe(0);
  });

  it("lets a moderator approve and reject what is waiting", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("Off topic.");
    const api = mockApi({
      ...routes(MODERATOR),
      [`POST ${COMMUNITY}submissions/share-9/approve/`]: () => json({}),
      [`POST ${COMMUNITY}submissions/share-9/reject/`]: () => json({}),
    });
    renderApp("/communities/com-1", makeSession());
    const user = userEvent.setup();

    const queue = await screen.findByRole("region", { name: "Opportunities waiting for review" });
    expect(await within(queue).findByText(/shared by Mia Member/)).toBeVisible();
    await user.click(within(queue).getByRole("button", { name: "Approve Data Analyst" }));
    await waitFor(() => expect(api.count(`POST ${COMMUNITY}submissions/share-9/approve/`)).toBe(1));

    await user.click(within(queue).getByRole("button", { name: "Reject Data Analyst" }));
    await waitFor(() =>
      expect(api.last(`POST ${COMMUNITY}submissions/share-9/reject/`)?.body).toEqual({
        reason: "Off topic.",
      }),
    );
  });

  it("does not reject when the reason prompt is cancelled", async () => {
    vi.spyOn(window, "prompt").mockReturnValue(null);
    const api = mockApi(routes(MODERATOR));
    renderApp("/communities/com-1", makeSession());

    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Reject Data Analyst" }));

    expect(api.calls.every((call) => call.key.startsWith("GET"))).toBe(true);
  });

  it("lets a moderator pin, unpin and remove what the community shows", async () => {
    const api = mockApi({
      ...routes(MODERATOR),
      [`POST ${COMMUNITY}submissions/share-1/feature/`]: () => json({}),
      [`POST ${COMMUNITY}submissions/share-2/unfeature/`]: () => json({}),
      [`POST ${COMMUNITY}submissions/share-1/remove/`]: () => json({}),
    });
    renderApp("/communities/com-1", makeSession());
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Pin to top Backend Engineer" }));
    await waitFor(() => expect(api.count(`POST ${COMMUNITY}submissions/share-1/feature/`)).toBe(1));
    await user.click(screen.getByRole("button", { name: "Unpin Frontend Engineer" }));
    await waitFor(() =>
      expect(api.count(`POST ${COMMUNITY}submissions/share-2/unfeature/`)).toBe(1),
    );
    await user.click(screen.getByRole("button", { name: "Remove Backend Engineer" }));
    await waitFor(() => expect(api.count(`POST ${COMMUNITY}submissions/share-1/remove/`)).toBe(1));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("cannot be undone"));
  });
});
