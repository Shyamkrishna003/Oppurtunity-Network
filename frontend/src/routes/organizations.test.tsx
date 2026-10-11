import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  Member,
  OrganizationDetail,
  OrganizationViewer,
  ReceivedInvitation,
} from "../features/organizations/types";
import { makeMe, makeSession } from "../test/fixtures";
import { apiError, json, mockApi, noContent } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const ORG = "/api/v1/organizations/org-1/";
const page = <T,>(results: T[]) => json({ results, next: null, previous: null });

const OUTSIDER: OrganizationViewer = {
  membership_id: null,
  role: null,
  is_public: null,
  can_manage: false,
  assignable_roles: [],
};
const OWNER: OrganizationViewer = {
  membership_id: "m-owner",
  role: "OWNER",
  is_public: true,
  can_manage: true,
  assignable_roles: ["ADMIN", "MEMBER", "OWNER", "RECRUITER"],
};
const ADMIN: OrganizationViewer = {
  membership_id: "m-admin",
  role: "ADMIN",
  is_public: true,
  can_manage: true,
  assignable_roles: ["MEMBER", "RECRUITER"],
};

function organization(viewer: OrganizationViewer = OUTSIDER): OrganizationDetail {
  return {
    id: "org-1",
    name: "Example Labs",
    slug: "example-labs",
    description: "We build things.",
    website: "https://example.com",
    industry: "Software",
    country_code: "IN",
    region: "Kerala",
    city: "Kochi",
    verification_status: "UNVERIFIED",
    status: "ACTIVE",
    member_count: 3,
    created_at: "2026-10-01T00:00:00Z",
    viewer,
  };
}

function member(id: string, name: string, role: Member["role"]): Member {
  return {
    id,
    user: { id: `u-${id}`, display_name: name, headline: "", avatar_url: null },
    role,
    is_public: true,
    joined_at: "2026-10-01T00:00:00Z",
  };
}

const MEMBERS = [
  member("m-owner", "Olivia Owner", "OWNER"),
  member("m-admin", "Adam Admin", "ADMIN"),
  member("m-member", "Mia Member", "MEMBER"),
];

function organizationRoutes(viewer: OrganizationViewer) {
  return {
    [`GET ${ORG}`]: () => json(organization(viewer)),
    [`GET ${ORG}members/`]: () => page(MEMBERS),
    [`GET ${ORG}invitations/`]: () => page([]),
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("organizations list", () => {
  it("lists organizations and searches through the URL", async () => {
    const api = mockApi({
      "GET /api/v1/organizations/": ({ url }) =>
        page(url.searchParams.get("q") === "kochi" ? [] : [organization()]),
    });
    const router = renderApp("/organizations");
    const user = userEvent.setup();

    expect(await screen.findByRole("link", { name: "Example Labs" })).toBeVisible();
    expect(screen.getByText("Software · Kochi, Kerala, IN · 3 members")).toBeVisible();
    // Visitors can browse but are not offered creation.
    expect(screen.queryByRole("link", { name: "Create organization" })).toBeNull();

    await user.type(screen.getByRole("searchbox"), "kochi");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("No organizations match that name.")).toBeVisible();
    expect(router.state.location.search).toBe("?q=kochi");
    expect(api.last("GET /api/v1/organizations/")?.url.searchParams.get("q")).toBe("kochi");
  });

  it("shows a signed-in user their own organizations and a way to create one", async () => {
    mockApi({
      "GET /api/v1/organizations/": () => page([]),
      "GET /api/v1/organizations/mine/": () =>
        json([
          {
            membership_id: "m-owner",
            organization: { id: "org-1", name: "Example Labs", slug: "example-labs" },
            role: "OWNER",
          },
        ]),
    });
    renderApp("/organizations", makeSession());

    const mine = await screen.findByRole("region", { name: "Your organizations" });
    expect(within(mine).getByRole("link", { name: "Example Labs" })).toBeVisible();
    expect(within(mine).getByText("Owner")).toBeVisible();
    expect(screen.getByRole("link", { name: "Create organization" })).toBeVisible();
    expect(await screen.findByText("No organizations yet.")).toBeVisible();
  });

  it("offers a retry when the list cannot be loaded", async () => {
    mockApi({ "GET /api/v1/organizations/": () => apiError(503, "error", "Service unavailable.") });
    renderApp("/organizations");

    expect(await screen.findByRole("alert", {}, { timeout: 5000 })).toHaveTextContent(
      "Service unavailable.",
    );
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });
});

describe("create organization", () => {
  it("creates the organization and opens its page", async () => {
    const api = mockApi({
      "POST /api/v1/organizations/": () => json(organization(OWNER), 201),
      ...organizationRoutes(OWNER),
    });
    const router = renderApp("/organizations/new", makeSession());
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Name"), "Example Labs");
    await user.type(screen.getByLabelText("Country code"), "in");
    await user.click(screen.getByRole("button", { name: "Create organization" }));

    expect(await screen.findByRole("heading", { name: "Example Labs" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/organizations/org-1");
    expect(api.last("POST /api/v1/organizations/")?.body).toMatchObject({
      name: "Example Labs",
      country_code: "in",
    });
  });

  it("tells an unverified user to confirm their email first", () => {
    mockApi({});
    renderApp("/organizations/new", makeSession(makeMe({ email_verified: false })));

    expect(screen.getByText(/Confirm your email address before creating/)).toBeVisible();
    expect(screen.queryByLabelText("Name")).toBeNull();
  });

  it("sends visitors to sign in", async () => {
    mockApi({});
    const router = renderApp("/organizations/new");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(router.state.location.search).toBe("?next=%2Forganizations%2Fnew");
  });
});

describe("organization page", () => {
  it("shows a visitor the details and members, without any controls", async () => {
    const api = mockApi(organizationRoutes(OUTSIDER));
    renderApp("/organizations/org-1");

    expect(await screen.findByRole("heading", { name: "Example Labs" })).toBeVisible();
    expect(screen.getByText("We build things.")).toBeVisible();
    expect(screen.getByRole("link", { name: "https://example.com" })).toHaveAttribute(
      "rel",
      "noopener noreferrer nofollow",
    );
    expect(await screen.findByText("Mia Member")).toBeVisible();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: /Remove|Edit details|Leave/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Invite people" })).toBeNull();
    expect(api.count(`GET ${ORG}invitations/`)).toBe(0);
  });

  it("lets an owner manage everyone but themselves", async () => {
    mockApi(organizationRoutes(OWNER));
    renderApp("/organizations/org-1", makeSession());

    expect(await screen.findByLabelText("Role of Adam Admin")).toHaveValue("ADMIN");
    expect(screen.getByLabelText("Role of Mia Member")).toHaveValue("MEMBER");
    expect(screen.queryByLabelText("Role of Olivia Owner")).toBeNull();
    expect(screen.getByRole("button", { name: "Transfer ownership to Mia Member" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Remove Adam Admin" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Invite people" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Leave organization" })).toBeVisible();
  });

  it("limits an admin to recruiters and members", async () => {
    mockApi(organizationRoutes(ADMIN));
    renderApp("/organizations/org-1", makeSession());

    const role = await screen.findByLabelText("Role of Mia Member");
    expect(
      within(role)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Recruiter", "Member"]);
    expect(screen.queryByLabelText("Role of Olivia Owner")).toBeNull();
    expect(screen.queryByLabelText("Role of Adam Admin")).toBeNull();
    expect(screen.queryByRole("button", { name: /Transfer ownership/ })).toBeNull();
    const inviteRole = screen.getByLabelText("Role");
    expect(within(inviteRole).getAllByRole("option")).toHaveLength(2);
  });

  it("changes a role and shows the server's refusal if it fails", async () => {
    let attempts = 0;
    const api = mockApi({
      ...organizationRoutes(OWNER),
      [`PATCH ${ORG}members/m-member/`]: () =>
        ++attempts === 1
          ? json(member("m-member", "Mia Member", "RECRUITER"))
          : apiError(403, "permission_denied", "You do not have permission to do this."),
    });
    renderApp("/organizations/org-1", makeSession());
    const user = userEvent.setup();

    await user.selectOptions(await screen.findByLabelText("Role of Mia Member"), "RECRUITER");
    await waitFor(() =>
      expect(api.last(`PATCH ${ORG}members/m-member/`)?.body).toEqual({ role: "RECRUITER" }),
    );

    await user.selectOptions(screen.getByLabelText("Role of Mia Member"), "ADMIN");
    expect(await screen.findByText("You do not have permission to do this.")).toBeVisible();
  });

  it("sends an invitation and reports a conflict", async () => {
    let attempts = 0;
    const api = mockApi({
      ...organizationRoutes(OWNER),
      [`POST ${ORG}invitations/`]: () =>
        ++attempts === 1
          ? json({ id: "i-1", email: "new@example.com", role: "MEMBER", status: "PENDING" }, 201)
          : apiError(409, "invitation_pending", "This address already has an open invitation."),
    });
    renderApp("/organizations/org-1", makeSession());
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Email address"), "new@example.com");
    await user.click(screen.getByRole("button", { name: "Send invitation" }));

    expect(await screen.findByText("Invitation sent to new@example.com.")).toBeVisible();
    expect(api.last(`POST ${ORG}invitations/`)?.body).toEqual({
      email: "new@example.com",
      role: "MEMBER",
    });
    expect(screen.getByLabelText("Email address")).toHaveValue("");

    await user.type(screen.getByLabelText("Email address"), "new@example.com");
    await user.click(screen.getByRole("button", { name: "Send invitation" }));
    expect(await screen.findByText("This address already has an open invitation.")).toBeVisible();
  });

  it("explains a missing organization", async () => {
    mockApi({});
    renderApp("/organizations/org-1");

    expect(await screen.findByRole("heading", { name: "Organization not found" })).toBeVisible();
  });
});

describe("invitation link", () => {
  const LINK = "/api/v1/organization-invitations/tok123/";
  const received: ReceivedInvitation = {
    organization: { id: "org-1", name: "Example Labs", slug: "example-labs" },
    role: "RECRUITER",
    status: "PENDING",
    expires_at: "2026-10-20T00:00:00Z",
    invited_by: "Olivia Owner",
  };

  it("accepts and opens the organization", async () => {
    const api = mockApi({
      [`GET ${LINK}`]: () => json(received),
      [`POST ${LINK}accept/`]: () =>
        json({ membership_id: "m-new", organization: received.organization, role: "RECRUITER" }),
      ...organizationRoutes({ ...OUTSIDER, role: "RECRUITER", membership_id: "m-new" }),
    });
    const router = renderApp("/organization-invitations/tok123", makeSession());

    expect(await screen.findByRole("heading", { name: "Join Example Labs?" })).toBeVisible();
    expect(screen.getByText(/Olivia Owner invited you/)).toBeVisible();
    await userEvent.setup().click(screen.getByRole("button", { name: "Accept" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/organizations/org-1"));
    expect(api.count(`POST ${LINK}accept/`)).toBe(1);
  });

  it("declines without joining", async () => {
    const api = mockApi({
      [`GET ${LINK}`]: () => json(received),
      [`POST ${LINK}decline/`]: noContent,
    });
    renderApp("/organization-invitations/tok123", makeSession());

    await userEvent.setup().click(await screen.findByRole("button", { name: "Decline" }));

    expect(await screen.findByRole("heading", { name: "Invitation declined" })).toBeVisible();
    expect(api.count(`POST ${LINK}accept/`)).toBe(0);
  });

  it("explains an invitation sent to a different address", async () => {
    mockApi({
      [`GET ${LINK}`]: () =>
        apiError(
          403,
          "invitation_email_mismatch",
          "This invitation was sent to a different email address.",
        ),
    });
    renderApp("/organization-invitations/tok123", makeSession());

    expect(await screen.findByRole("alert")).toHaveTextContent("sent to a different email address");
    expect(screen.getByText("You are signed in as ada@example.com.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
  });

  it("does not offer to accept a closed invitation", async () => {
    mockApi({ [`GET ${LINK}`]: () => json({ ...received, status: "EXPIRED" }) });
    renderApp("/organization-invitations/tok123", makeSession());

    expect(await screen.findByRole("alert")).toHaveTextContent("This invitation has expired.");
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
  });

  it("blocks accepting until the email address is confirmed", async () => {
    mockApi({ [`GET ${LINK}`]: () => json(received) });
    renderApp("/organization-invitations/tok123", makeSession(makeMe({ email_verified: false })));

    expect(await screen.findByRole("button", { name: "Accept" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Decline" })).toBeEnabled();
  });
});
