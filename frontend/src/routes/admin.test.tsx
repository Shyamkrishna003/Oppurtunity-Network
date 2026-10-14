import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PlatformTotals } from "../features/admin/api";
import type { AuditEntry } from "../features/audit/api";
import type { CommunityReportDetail } from "../features/moderation/api";
import type { OpportunityDetail } from "../features/opportunities/types";
import { makeMe, makeSession, makeViewer } from "../test/fixtures";
import { apiError, json, mockApi, noContent } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const page = <T,>(results: T[]) => json({ results, next: null, previous: null });
const ADMIN = makeSession(makeMe({ platform_role: "ADMIN" }));
const grace = { id: "u-2", display_name: "Grace Hopper", headline: "", avatar_url: null };

beforeEach(() => vi.spyOn(window, "confirm").mockReturnValue(true));
afterEach(() => vi.unstubAllGlobals());

describe("a community's reports", () => {
  const QUEUE = "GET /api/v1/communities/c-1/reports/";
  const ONE = "/api/v1/communities/c-1/reports/r-1/";

  function report(overrides: Partial<CommunityReportDetail> = {}): CommunityReportDetail {
    return {
      id: "r-1",
      target: {
        type: "OPPORTUNITY",
        id: "opp-1",
        name: "Easy money",
        url: "/opportunities/opp-1",
      },
      category: "SCAM",
      description: "Asks for a fee.",
      status: "OPEN",
      created_at: "2026-10-10T09:00:00Z",
      resolved_at: null,
      assigned_to: null,
      resolution_note: "",
      in_progress_on_target: 2,
      shown_in_community: true,
      can_decide: true,
      ...overrides,
    };
  }

  it("lets a member send a report to the moderators of a community that shows it", async () => {
    const job = {
      id: "opp-1",
      type: "JOB",
      title: "Easy money",
      description: "Send us a fee.",
      status: "PUBLISHED",
      visibility: "PUBLIC",
      moderation_status: "VISIBLE",
      communities: [
        { id: "c-1", name: "Kochi Developers", slug: "kochi" },
        { id: "c-2", name: "Not Mine", slug: "not-mine" },
      ],
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
      posted_by: grace,
      skills: [],
      event: null,
      job: {
        department: "",
        employment_type: "FULL_TIME",
        experience_level: "MID",
        salary_min: null,
        salary_max: null,
        salary_currency: "",
        salary_period: "",
        application_method: "EXTERNAL",
        external_url: "https://example.com/apply",
        openings: 1,
      },
      viewer: makeViewer(),
    } as unknown as OpportunityDetail;
    const api = mockApi({
      "GET /api/v1/opportunities/opp-1/": () => json(job),
      "GET /api/v1/communities/mine/": () =>
        json([
          {
            membership_id: "m-1",
            community: { id: "c-1", name: "Kochi Developers", slug: "kochi" },
            role: "MEMBER",
            status: "ACTIVE",
          },
        ]),
      "POST /api/v1/reports/": () => json(report(), 201),
    });
    const user = userEvent.setup();
    renderApp("/opportunities/opp-1", makeSession());

    await user.click(await screen.findByRole("button", { name: "Report this job" }));
    const recipient = await screen.findByLabelText("Who should look at it?");
    // Only communities the viewer belongs to are offered.
    expect(within(recipient).getAllByRole("option")).toHaveLength(2);
    await user.selectOptions(recipient, "c-1");
    await user.selectOptions(screen.getByLabelText("What is wrong with it?"), "SCAM");
    await user.click(screen.getByRole("button", { name: "Send report" }));

    await screen.findByText(/A moderator will look at it/);
    expect(api.last("POST /api/v1/reports/")?.body).toEqual({
      target_type: "OPPORTUNITY",
      target_id: "opp-1",
      category: "SCAM",
      description: "",
      community_id: "c-1",
    });
  });

  it("lists what is waiting without naming who reported, and explains itself to others", async () => {
    const api = mockApi({ [QUEUE]: () => page([report()]) });
    const user = userEvent.setup();
    renderApp("/communities/c-1/reports", makeSession());

    const link = await screen.findByRole("link", { name: "Easy money" });
    expect(link).toHaveAttribute("href", "/communities/c-1/reports/r-1");
    expect(screen.getByText(/Who\s+reported is not shown/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Show"), "ALL");
    await waitFor(() => expect(api.last(QUEUE)?.url.search).toBe(""));
    const first = api.calls.find((call) => call.key === QUEUE);
    expect(first?.url.search).toBe("?status=OPEN");
  });

  it("is refused to people who are not the community's moderators", async () => {
    mockApi({ [QUEUE]: () => apiError(403, "permission_denied", "No.") });
    renderApp("/communities/c-1/reports", makeSession());

    expect(
      await screen.findByText("This page is for the community's moderators."),
    ).toBeInTheDocument();
  });

  it("removes what was reported from the community, with a reason", async () => {
    let current = report();
    const api = mockApi({
      [`GET ${ONE}`]: () => json(current),
      [`POST ${ONE}remove/`]: () => {
        current = report({
          status: "ACTION_TAKEN",
          shown_in_community: false,
          resolution_note: "Asks members for a fee.",
        });
        return json(current);
      },
    });
    const user = userEvent.setup();
    renderApp("/communities/c-1/reports/r-1", makeSession());

    expect(await screen.findByText(/by a member/)).toBeInTheDocument();
    expect(screen.queryByText("Grace Hopper")).toBeNull();
    expect(screen.getByText(/settles the other 1 waiting/)).toBeInTheDocument();
    const remove = screen.getByRole("button", { name: "Remove from this community" });
    expect(remove).toBeDisabled();
    await user.type(screen.getByLabelText("Reason"), "Asks members for a fee.");
    await user.click(remove);

    expect(await screen.findByText("Action taken")).toBeInTheDocument();
    expect(window.confirm).toHaveBeenCalled();
    expect(api.last(`POST ${ONE}remove/`)?.body).toEqual({ reason: "Asks members for a fee." });
    // Decided: nothing more is offered.
    expect(screen.queryByRole("heading", { name: "Decide" })).toBeNull();
  });

  it("passes a report up to the platform and returns to the list", async () => {
    const api = mockApi({
      [`GET ${ONE}`]: () => json(report({ shown_in_community: false })),
      [`POST ${ONE}escalate/`]: () => noContent(),
      [QUEUE]: () => page([]),
    });
    const user = userEvent.setup();
    renderApp("/communities/c-1/reports/r-1", makeSession());

    await user.click(
      await screen.findByRole("button", { name: "Pass to the platform's moderators" }),
    );

    expect(await screen.findByText("Nothing is waiting. Well done.")).toBeInTheDocument();
    expect(api.count(`POST ${ONE}escalate/`)).toBe(1);
    // Nothing to remove once the community no longer shows it.
    expect(screen.queryByRole("button", { name: "Remove from this community" })).toBeNull();
  });

  it("does not let a moderator decide a report about their own posting", async () => {
    mockApi({ [`GET ${ONE}`]: () => json(report({ can_decide: false })) });
    renderApp("/communities/c-1/reports/r-1", makeSession());

    expect(await screen.findByText(/not yours to decide/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "No action needed" })).toBeNull();
  });
});

describe("the audit log", () => {
  const ALL = "GET /api/v1/admin/audit-logs/";
  const entry = (overrides: Partial<AuditEntry> = {}): AuditEntry => ({
    id: "a-1",
    action: "application.status_changed",
    actor: { id: "u-2", display_name: "Grace Hopper" },
    actor_type: "USER",
    target_type: "applications.application",
    target_id: "app-1",
    metadata: { from: "APPLIED", to: "INTERVIEW", nested: { secret: 1 } },
    created_at: "2026-10-11T09:00:00Z",
    ...overrides,
  });

  it("shows an organization's owners what was done, in words", async () => {
    mockApi({
      "GET /api/v1/organizations/o-1/audit-logs/": () =>
        page([
          entry(),
          entry({
            id: "a-2",
            action: "opportunity.expired",
            actor: null,
            actor_type: "SYSTEM",
            target_type: "opportunities.opportunity",
            target_id: "opp-1",
            metadata: {},
          }),
        ]),
    });
    renderApp("/organizations/o-1/audit", makeSession());

    expect(await screen.findByText("Application: status changed")).toBeInTheDocument();
    expect(screen.getByText("from: APPLIED · to: INTERVIEW")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Grace Hopper" })).toHaveAttribute(
      "href",
      "/users/u-2",
    );
    expect(screen.getByText(/by\s+the system/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "open what it was done to" })).toHaveAttribute(
      "href",
      "/opportunities/opp-1",
    );
  });

  it("tells anyone but a community's owners that it is not theirs to read", async () => {
    mockApi({
      "GET /api/v1/communities/c-1/audit-logs/": () => apiError(403, "permission_denied", "No."),
    });
    renderApp("/communities/c-1/audit", makeSession());

    expect(await screen.findByText("This record is for the community's owners.")).toBeVisible();
  });

  it("lets an admin narrow the whole trail through the address", async () => {
    const api = mockApi({
      [ALL]: ({ url }) =>
        page(
          url.searchParams.get("action")
            ? [entry({ action: "report.filed", ip: "10.0.0.7", request_id: "req-9" })]
            : [],
        ),
    });
    const user = userEvent.setup();
    renderApp("/admin/audit", ADMIN);

    expect(await screen.findByText("Nothing has been recorded here.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Action"), "report.");
    await user.type(screen.getByLabelText("Done by"), "grace@example.com");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("Report: filed")).toBeInTheDocument();
    expect(screen.getByText(/From 10\.0\.0\.7/)).toBeInTheDocument();
    const search = api.last(ALL)?.url.searchParams;
    expect(search?.get("action")).toBe("report.");
    expect(search?.get("actor_email")).toBe("grace@example.com");
    expect(search?.has("target_id")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Show everything" }));
    // Back to the unfiltered list, and the form is empty again.
    expect(await screen.findByText("Nothing has been recorded here.")).toBeInTheDocument();
    expect(screen.getByLabelText("Action")).toHaveValue("");
  });
});

describe("the admin page", () => {
  const STATS = "GET /api/v1/admin/stats/";
  const totals: PlatformTotals = {
    generated_at: "2026-10-14T09:00:00Z",
    users: { total: 1200, verified: 1100, joined_recently: 40, suspended: 2 },
    organizations: { total: 30, verified: 12 },
    communities: { total: 18 },
    opportunities: {
      published: 85,
      jobs: 60,
      events: 25,
      published_recently: 9,
      hidden_or_removed: 3,
    },
    outcomes: {
      applications: 410,
      hires: 17,
      registrations: 220,
      attendances: 150,
      referrals: 33,
      referral_joins: 4,
    },
    reports: { waiting: 1, under_review: 0 },
  };

  it("shows the platform's numbers with outcomes first", async () => {
    const api = mockApi({ [STATS]: () => json(totals) });
    const user = userEvent.setup();
    renderApp("/admin", ADMIN);

    const outcomes = await screen.findByRole("region", { name: "Outcomes" });
    expect(within(outcomes).getByText("Hires").nextElementSibling).toHaveTextContent("17");
    const people = screen.getByRole("region", { name: "People and places" });
    expect(within(people).getByText("People").nextElementSibling).toHaveTextContent(
      new Intl.NumberFormat().format(1200),
    );
    const sections = screen
      .getAllByRole("region")
      .map((region) => region.getAttribute("aria-labelledby"));
    expect(sections[0]).toBe("figures-outcomes");
    expect(screen.getByRole("link", { name: "1 report is waiting" })).toHaveAttribute(
      "href",
      "/moderation",
    );
    expect(screen.getByRole("link", { name: "Audit log" })).toHaveAttribute("href", "/admin/audit");

    await user.click(screen.getByRole("button", { name: "Count again" }));
    await waitFor(() => expect(api.count(STATS)).toBe(2));
  });

  it("is in the menu for admins only, and refused to everyone else", async () => {
    mockApi({ [STATS]: () => apiError(403, "permission_denied", "No.") });
    renderApp("/admin", makeSession(makeMe({ platform_role: "MODERATOR" })));

    expect(await screen.findByText("This page is for the platform's admins.")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
    expect(screen.getByRole("link", { name: "Moderation" })).toBeInTheDocument();
  });
});
