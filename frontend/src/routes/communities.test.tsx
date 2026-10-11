import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CommunityDetail,
  CommunityMember,
  CommunityViewer,
} from "../features/communities/types";
import { makeMe, makeSession } from "../test/fixtures";
import { apiError, json, mockApi, noContent } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const COMMUNITY = "/api/v1/communities/com-1/";
const page = <T,>(results: T[]) => json({ results, next: null, previous: null });

const NOBODY: CommunityViewer = {
  membership_id: null,
  status: null,
  role: null,
  join_action: "join",
  can_manage: false,
  can_review_requests: false,
  assignable_roles: [],
};
const MEMBER: CommunityViewer = {
  ...NOBODY,
  membership_id: "m-me",
  status: "ACTIVE",
  role: "MEMBER",
  join_action: null,
};
const MODERATOR: CommunityViewer = { ...MEMBER, role: "MODERATOR", can_review_requests: true };
const OWNER: CommunityViewer = {
  ...MEMBER,
  role: "OWNER",
  can_manage: true,
  can_review_requests: true,
  assignable_roles: ["ADMIN", "MEMBER", "MODERATOR", "OWNER"],
};

function community(
  viewer: CommunityViewer,
  overrides: Partial<CommunityDetail> = {},
): CommunityDetail {
  return {
    id: "com-1",
    name: "Kochi Developers",
    slug: "kochi-developers",
    description: "Developers in and around Kochi.",
    category: "Technology",
    join_policy: "OPEN",
    posting_policy: "MEMBERS_WITH_APPROVAL",
    visibility: "PUBLIC",
    is_verified: false,
    status: "ACTIVE",
    member_count: 3,
    created_at: "2026-10-01T00:00:00Z",
    rules: [{ title: "Be kind", body: "No personal attacks." }],
    viewer,
    ...overrides,
  };
}

function person(
  id: string,
  name: string,
  status: CommunityMember["status"],
  role: CommunityMember["role"] = "MEMBER",
): CommunityMember {
  return {
    id,
    user: { id: `u-${id}`, display_name: name, headline: "", avatar_url: null },
    role,
    status,
    joined_at: status === "ACTIVE" ? "2026-10-01T00:00:00Z" : null,
  };
}

const PEOPLE: Record<string, CommunityMember[]> = {
  ACTIVE: [
    person("m-me", "Ada Lovelace", "ACTIVE", "OWNER"),
    person("m-mod", "Mo Moderator", "ACTIVE", "MODERATOR"),
    person("m-member", "Mia Member", "ACTIVE"),
  ],
  PENDING: [person("m-pending", "Pat Pending", "PENDING")],
  INVITED: [person("m-invited", "Ivy Invited", "INVITED")],
  BANNED: [person("m-banned", "Ben Banned", "BANNED")],
};

function routes(viewer: CommunityViewer, overrides: Partial<CommunityDetail> = {}) {
  return {
    [`GET ${COMMUNITY}`]: () => json(community(viewer, overrides)),
    [`GET ${COMMUNITY}members/`]: ({ url }: { url: URL }) =>
      page(PEOPLE[url.searchParams.get("status") ?? "ACTIVE"] ?? []),
    "GET /api/v1/communities/mine/": () => json([]),
  };
}

beforeEach(() => vi.spyOn(window, "confirm").mockReturnValue(true));
afterEach(() => vi.unstubAllGlobals());

describe("communities list", () => {
  it("lists communities for a visitor and searches through the URL", async () => {
    const api = mockApi({
      "GET /api/v1/communities/": ({ url }) =>
        page(url.searchParams.get("q") === "react" ? [] : [community(NOBODY)]),
    });
    const router = renderApp("/communities");
    const user = userEvent.setup();

    expect(await screen.findByRole("link", { name: "Kochi Developers" })).toBeVisible();
    expect(screen.getByText("Technology · 3 members · Anyone can join")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Create community" })).toBeNull();

    await user.type(screen.getByRole("searchbox"), "react");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("No communities match that name.")).toBeVisible();
    expect(router.state.location.search).toBe("?q=react");
    expect(api.last("GET /api/v1/communities/")?.url.searchParams.get("q")).toBe("react");
  });

  it("shows a signed-in user their memberships, invitations and requests", async () => {
    const ref = (id: string, name: string) => ({ id, name, slug: id });
    mockApi({
      "GET /api/v1/communities/": () => page([]),
      "GET /api/v1/communities/mine/": () =>
        json([
          { membership_id: "1", community: ref("a", "Alpha"), role: "ADMIN", status: "ACTIVE" },
          { membership_id: "2", community: ref("b", "Beta"), role: "MEMBER", status: "INVITED" },
          { membership_id: "3", community: ref("c", "Gamma"), role: "MEMBER", status: "PENDING" },
        ]),
    });
    renderApp("/communities", makeSession());

    const mine = await screen.findByRole("region", { name: "Your communities" });
    const rows = within(mine)
      .getAllByRole("listitem")
      .map((row) => row.textContent);
    expect(rows).toEqual(["AlphaAdmin", "BetaInvited", "GammaRequest pending"]);
    expect(screen.getByRole("link", { name: "Create community" })).toBeVisible();
  });
});

describe("create community", () => {
  it("creates the community with the chosen policies and opens it", async () => {
    const api = mockApi({
      "POST /api/v1/communities/": () => json(community(OWNER), 201),
      ...routes(OWNER),
    });
    const router = renderApp("/communities/new", makeSession());
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Name"), "Kochi Developers");
    await user.selectOptions(screen.getByLabelText("How people join"), "APPROVAL");
    await user.selectOptions(screen.getByLabelText("Who can see it"), "PRIVATE");
    expect(screen.getByText(/A private community cannot be found/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Create community" }));

    expect(await screen.findByRole("heading", { name: "Kochi Developers" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/communities/com-1");
    expect(api.last("POST /api/v1/communities/")?.body).toMatchObject({
      name: "Kochi Developers",
      join_policy: "APPROVAL",
      visibility: "PRIVATE",
      posting_policy: "MEMBERS_WITH_APPROVAL",
    });
  });

  it("tells an unverified user to confirm their email first", () => {
    mockApi({});
    renderApp("/communities/new", makeSession(makeMe({ email_verified: false })));

    expect(screen.getByText(/Confirm your email address before creating/)).toBeVisible();
    expect(screen.queryByLabelText("Name")).toBeNull();
  });
});

describe("community page", () => {
  it("shows a visitor the details and rules and asks them to sign in", async () => {
    const api = mockApi(routes(NOBODY));
    renderApp("/communities/com-1");

    expect(await screen.findByRole("heading", { name: "Kochi Developers" })).toBeVisible();
    expect(screen.getByText("Be kind")).toBeVisible();
    const membership = screen.getByRole("region", { name: "Your membership" });
    expect(within(membership).getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/login?next=%2Fcommunities%2Fcom-1",
    );
    expect(screen.queryByRole("button", { name: "Join community" })).toBeNull();
    expect(screen.queryByRole("heading", { name: /Members/ })).toBeNull();
    expect(api.count(`GET ${COMMUNITY}members/`)).toBe(0);
  });

  it.each([
    ["join", "Join community"],
    ["request", "Ask to join"],
    ["accept", "Accept invitation"],
  ] as const)("offers the %s action and performs it", async (joinAction, label) => {
    const api = mockApi({
      ...routes({ ...NOBODY, join_action: joinAction }),
      [`POST ${COMMUNITY}join/`]: () => json(community(MEMBER)),
    });
    renderApp("/communities/com-1", makeSession());

    await userEvent.setup().click(await screen.findByRole("button", { name: label }));

    await waitFor(() => expect(api.count(`POST ${COMMUNITY}join/`)).toBe(1));
  });

  it("explains the states in which joining is not possible", async () => {
    mockApi(routes({ ...NOBODY, join_action: null }, { join_policy: "INVITE_ONLY" }));
    renderApp("/communities/com-1", makeSession());

    expect(
      await screen.findByText("This community can only be joined by invitation."),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: /Join|Ask|Accept/ })).toBeNull();
  });

  it("lets someone with a pending request withdraw it", async () => {
    const api = mockApi({
      ...routes({ ...NOBODY, membership_id: "m-me", status: "PENDING", join_action: null }),
      [`POST ${COMMUNITY}leave/`]: noContent,
    });
    renderApp("/communities/com-1", makeSession());

    expect(await screen.findByText(/waiting for an admin to review/)).toBeVisible();
    await userEvent.setup().click(screen.getByRole("button", { name: "Withdraw request" }));

    await waitFor(() => expect(api.count(`POST ${COMMUNITY}leave/`)).toBe(1));
  });

  it("blocks joining until the email address is confirmed", async () => {
    mockApi(routes(NOBODY));
    renderApp("/communities/com-1", makeSession(makeMe({ email_verified: false })));

    expect(await screen.findByRole("button", { name: "Join community" })).toBeDisabled();
    expect(
      screen.getByText("Confirm your email address before joining a community."),
    ).toBeVisible();
  });

  it("shows an ordinary member the member list without any controls", async () => {
    const api = mockApi(routes(MEMBER));
    renderApp("/communities/com-1", makeSession());

    expect(await screen.findByText("Mia Member")).toBeVisible();
    expect(screen.getByRole("button", { name: "Leave community" })).toBeVisible();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: /Remove|Ban|Approve|Edit/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: /Requests to join|Invited|Banned/ })).toBeNull();
    const requested = api.calls
      .filter((call) => call.key === `GET ${COMMUNITY}members/`)
      .map((call) => call.url.searchParams.get("status"));
    expect(requested).toEqual(["ACTIVE"]);
  });

  it("lets a moderator approve requests but nothing more", async () => {
    const api = mockApi({
      ...routes(MODERATOR),
      [`POST ${COMMUNITY}members/m-pending/approve/`]: () =>
        json(person("m-pending", "Pat Pending", "ACTIVE")),
    });
    renderApp("/communities/com-1", makeSession());
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Approve Pat Pending" }));

    await waitFor(() => expect(api.count(`POST ${COMMUNITY}members/m-pending/approve/`)).toBe(1));
    expect(screen.queryByRole("button", { name: "Reject Pat Pending" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Remove|Ban/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: /Invited|Banned/ })).toBeNull();
  });

  it("gives an owner every management section and action", async () => {
    mockApi(routes(OWNER));
    renderApp("/communities/com-1", makeSession());

    expect(await screen.findByRole("button", { name: "Reject Pat Pending" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Approve Pat Pending" })).toBeVisible();
    expect(await screen.findByLabelText("Role of Mo Moderator")).toHaveValue("MODERATOR");
    expect(screen.queryByLabelText("Role of Ada Lovelace")).toBeNull(); // not their own
    expect(screen.getByRole("button", { name: "Ban Mia Member" })).toBeVisible();
    expect(
      await screen.findByRole("button", { name: "Withdraw invitation Ivy Invited" }),
    ).toBeVisible();
    expect(await screen.findByRole("button", { name: "Lift ban Ben Banned" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Edit community" })).toBeVisible();
  });

  it("bans a member after confirmation and shows a refusal from the server", async () => {
    const api = mockApi({
      ...routes(OWNER),
      [`POST ${COMMUNITY}members/m-member/ban/`]: () =>
        apiError(403, "permission_denied", "You do not have permission to do this."),
    });
    renderApp("/communities/com-1", makeSession());

    await userEvent.setup().click(await screen.findByRole("button", { name: "Ban Mia Member" }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("Ban Mia Member?"));
    expect(await screen.findByText("You do not have permission to do this.")).toBeVisible();
    expect(api.count(`POST ${COMMUNITY}members/m-member/ban/`)).toBe(1);
  });

  it("does nothing when a confirmation is cancelled", async () => {
    vi.mocked(window.confirm).mockReturnValue(false);
    const api = mockApi(routes(OWNER));
    renderApp("/communities/com-1", makeSession());

    await userEvent.setup().click(await screen.findByRole("button", { name: "Ban Mia Member" }));

    expect(window.confirm).toHaveBeenCalled();
    expect(api.count(`POST ${COMMUNITY}members/m-member/ban/`)).toBe(0);
  });

  it("edits, reorders and saves the rules as one list", async () => {
    const api = mockApi({
      ...routes(OWNER),
      [`PUT ${COMMUNITY}rules/`]: () => json(community(OWNER)),
    });
    renderApp("/communities/com-1", makeSession());
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Edit rules" }));
    await user.click(screen.getByRole("button", { name: "Add rule" }));
    expect(screen.getByRole("button", { name: "Save rules" })).toBeDisabled(); // untitled rule
    await user.type(screen.getByLabelText("Rule 2"), "Stay on topic");
    await user.click(screen.getByRole("button", { name: "Move up rule 2" }));
    await user.click(screen.getByRole("button", { name: "Save rules" }));

    await waitFor(() =>
      expect(api.last(`PUT ${COMMUNITY}rules/`)?.body).toEqual({
        rules: [
          { title: "Stay on topic", body: "" },
          { title: "Be kind", body: "No personal attacks." },
        ],
      }),
    );
  });

  it("explains a community that is missing or private", async () => {
    mockApi({});
    renderApp("/communities/com-1", makeSession());

    expect(await screen.findByRole("heading", { name: "Community not found" })).toBeVisible();
    expect(screen.getByText(/it is private and you are not a member/)).toBeVisible();
  });
});

describe("inviting from a profile", () => {
  const PROFILE = "/api/v1/users/u-9/";
  const profile = {
    id: "u-9",
    is_self: false,
    display_name: "Grace Hopper",
    headline: "",
    bio: "",
    avatar_url: null,
    country_code: "",
    region: "",
    city: "",
    work_mode_preference: "",
    experience_level: "",
    skills: { has: [], interested: [] },
    email: null,
    experiences: [],
    educations: [],
  };
  const mine = (role: string) =>
    json([
      {
        membership_id: "m-me",
        community: { id: "com-1", name: "Kochi Developers", slug: "kochi-developers" },
        role,
        status: "ACTIVE",
      },
    ]);

  it("lets a community admin invite the person", async () => {
    const api = mockApi({
      [`GET ${PROFILE}`]: () => json(profile),
      "GET /api/v1/communities/mine/": () => mine("ADMIN"),
      [`POST ${COMMUNITY}invitations/`]: () =>
        json(person("m-new", "Grace Hopper", "INVITED"), 201),
    });
    renderApp("/users/u-9", makeSession());
    const user = userEvent.setup();

    await user.selectOptions(await screen.findByLabelText("Community"), "com-1");
    await user.click(screen.getByRole("button", { name: "Invite" }));

    expect(
      await screen.findByText("Grace Hopper has been invited to Kochi Developers."),
    ).toBeVisible();
    expect(api.last(`POST ${COMMUNITY}invitations/`)?.body).toEqual({ user_id: "u-9" });
  });

  it("is not offered to people who do not run a community", async () => {
    mockApi({
      [`GET ${PROFILE}`]: () => json(profile),
      "GET /api/v1/communities/mine/": () => mine("MODERATOR"),
    });
    renderApp("/users/u-9", makeSession());

    expect(await screen.findByRole("heading", { name: "Grace Hopper" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Invite to a community" })).toBeNull();
  });
});
