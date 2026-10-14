import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ModerationAction,
  MyReport,
  Report,
  ReportDetail,
  TargetDetail,
} from "../features/moderation/api";
import type { OpportunityDetail } from "../features/opportunities/types";
import { makeMe, makeSession, makeViewer } from "../test/fixtures";
import { apiError, json, mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const page = <T,>(results: T[]) => json({ results, next: null, previous: null });
const QUEUE = "GET /api/v1/moderation/reports/";
const ONE = "/api/v1/moderation/reports/r-1/";
const MODERATOR = makeSession(makeMe({ platform_role: "MODERATOR" }));

const target = {
  type: "OPPORTUNITY" as const,
  id: "opp-1",
  name: "Easy money",
  url: "/opportunities/opp-1",
};
const grace = { id: "u-2", display_name: "Grace Hopper", headline: "", avatar_url: null };

function report(overrides: Partial<ReportDetail> = {}): ReportDetail {
  return {
    id: "r-1",
    target,
    category: "SCAM",
    description: "Asks for money to apply.",
    status: "OPEN",
    created_at: "2026-10-10T09:00:00Z",
    resolved_at: null,
    reporter: grace,
    assigned_to: null,
    resolution_note: "",
    in_progress_on_target: 1,
    actions: [],
    available_actions: ["HIDE", "REMOVE"],
    ...overrides,
  };
}

function job(viewer = makeViewer()): OpportunityDetail {
  return {
    id: "opp-1",
    type: "JOB",
    title: "Easy money",
    description: "Send us a fee.",
    status: "PUBLISHED",
    visibility: "PUBLIC",
    moderation_status: "VISIBLE",
    communities: [],
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
    viewer,
  };
}

beforeEach(() => vi.spyOn(window, "confirm").mockReturnValue(true));
afterEach(() => vi.unstubAllGlobals());

describe("reporting", () => {
  const JOB = "GET /api/v1/opportunities/opp-1/";

  it("sends a report from the page of what is being reported", async () => {
    const api = mockApi({
      [JOB]: () => json(job()),
      "POST /api/v1/reports/": () => json({ id: "r-1" }, 201),
    });
    renderApp("/opportunities/opp-1", makeSession());
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Report this job" }));
    const form = screen.getByRole("region", { name: "Report this job" });
    expect(within(form).getByText(/is not told it was you/)).toBeVisible();
    const send = within(form).getByRole("button", { name: "Send report" });
    expect(send).toBeDisabled(); // nothing chosen yet
    await user.selectOptions(within(form).getByLabelText("What is wrong with it?"), "SCAM");
    await user.type(within(form).getByLabelText(/Anything that helps/), "  Asks for a fee.  ");
    await user.click(send);

    expect(await screen.findByText(/A moderator will look at it/)).toBeVisible();
    expect(api.last("POST /api/v1/reports/")?.body).toEqual({
      target_type: "OPPORTUNITY",
      target_id: "opp-1",
      category: "SCAM",
      description: "Asks for a fee.",
    });
    expect(screen.queryByRole("button", { name: "Report this job" })).toBeNull();
  });

  it("says when the same thing was already reported, and can be cancelled", async () => {
    const api = mockApi({
      [JOB]: () => json(job()),
      "POST /api/v1/reports/": () => apiError(409, "already_reported", "Already reported."),
    });
    renderApp("/opportunities/opp-1", makeSession());
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Report this job" }));
    await user.selectOptions(screen.getByLabelText("What is wrong with it?"), "SPAM");
    await user.click(screen.getByRole("button", { name: "Send report" }));
    expect(await screen.findByText(/You have already reported this/)).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("button", { name: "Report this job" })).toBeVisible();
    expect(api.count("POST /api/v1/reports/")).toBe(1);
  });

  it("is not offered to visitors or to the people who run what is shown", async () => {
    mockApi({ [JOB]: () => json(job()) });
    renderApp("/opportunities/opp-1");
    await screen.findByRole("heading", { name: "Easy money" });
    expect(screen.queryByRole("button", { name: /Report this/ })).toBeNull();

    cleanup();
    vi.unstubAllGlobals();
    mockApi({
      [JOB]: () => json(job(makeViewer({ can_manage: true, editable_fields: [] }))),
      [`${JOB}communities/`]: () => json([]),
      [`${JOB}communities/options/`]: () => json([]),
    });
    renderApp("/opportunities/opp-1", makeSession());
    // Signed in and looking at their own job: the manager's panel is there, Report is not.
    expect(await screen.findByRole("heading", { name: "Manage" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /Report this/ })).toBeNull();
  });

  it("lists my reports with only whether they have been reviewed", async () => {
    const mine = (overrides: Partial<MyReport>): MyReport => ({
      id: "r-1",
      target,
      category: "SCAM",
      description: "Asks for money to apply.",
      status: "OPEN",
      created_at: "2026-10-10T09:00:00Z",
      resolved_at: null,
      ...overrides,
    });
    const reports = [
      mine({ status: "DISMISSED" }),
      mine({ id: "r-2", target: { ...target, name: "Another job" } }),
    ];
    mockApi({ "GET /api/v1/reports/mine/": () => page(reports) });
    renderApp("/reports", makeSession());

    const list = await screen.findByRole("region", { name: "Your reports" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Easy money");
    expect(rows[0]).toHaveTextContent("Opportunity · Scam or fraud");
    // Dismissed and acted-on read the same to the person who reported.
    expect(rows[0]).toHaveTextContent("Reviewed");
    expect(rows[0]).not.toHaveTextContent(/No action|Dismissed/);
    expect(rows[1]).toHaveTextContent("Waiting");
  });
});

describe("the moderation queue", () => {
  const row = (overrides: Partial<Report> = {}): Report => ({ ...report(), ...overrides });

  it("shows waiting reports first and filters through the address", async () => {
    const api = mockApi({
      [QUEUE]: ({ url }) =>
        page(
          url.searchParams.get("status") === "OPEN"
            ? [row(), row({ id: "r-2", assigned_to: grace, status: "UNDER_REVIEW" })]
            : [row({ id: "r-3", status: "DISMISSED" })],
        ),
    });
    const router = renderApp("/moderation", MODERATOR);
    const user = userEvent.setup();

    const list = await screen.findByRole("region", { name: "Reports" });
    const rows = await within(list).findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByRole("link")).toHaveAttribute("href", "/moderation/reports/r-1");
    expect(rows[0]).toHaveTextContent("Opportunity · Scam or fraud");
    expect(rows[0]).toHaveTextContent("by Grace Hopper");
    expect(rows[1]).toHaveTextContent("With Grace Hopper");
    expect(api.last(QUEUE)?.url.searchParams.get("status")).toBe("OPEN");

    await user.selectOptions(within(list).getByLabelText("Show"), "DISMISSED");
    await waitFor(() => expect(router.state.location.search).toBe("?status=DISMISSED"));
    await waitFor(() =>
      expect(within(list).getByRole("listitem")).toHaveTextContent("No action needed"),
    );
  });

  it("links from the menu for moderators only, and explains itself to anyone else", async () => {
    mockApi({ [QUEUE]: () => page([]) });
    renderApp("/moderation", MODERATOR);
    expect(await screen.findByText("Nothing is waiting. Well done.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Moderation" })).toHaveAttribute("href", "/moderation");
  });

  it("is refused to people who are not moderators", async () => {
    mockApi({ [QUEUE]: () => apiError(403, "permission_denied", "No.") });
    renderApp("/moderation", makeSession());

    expect(await screen.findByText(/for the platform's moderators/)).toBeVisible();
    expect(screen.queryByRole("link", { name: "Moderation" })).toBeNull();
    expect(screen.getByRole("link", { name: "My reports" })).toHaveAttribute("href", "/reports");
  });
});

describe("deciding a report", () => {
  it("shows what was reported and hides it with a reason the owners will see", async () => {
    const hidden = report({
      status: "ACTION_TAKEN",
      available_actions: [],
      actions: [
        {
          id: "a-1",
          action_type: "HIDE",
          reason: "Asks applicants for a fee.",
          expires_at: null,
          actor: grace,
          created_at: "2026-10-11T09:00:00Z",
        },
      ],
    });
    // The page asks again after a decision, so the server answers with what it now holds.
    let current = report({ in_progress_on_target: 3 });
    const api = mockApi({
      [`GET ${ONE}`]: () => json(current),
      [`POST ${ONE}resolve/`]: () => {
        current = hidden;
        return json(hidden);
      },
      [QUEUE]: () => page([]),
    });
    renderApp("/moderation/reports/r-1", MODERATOR);
    const user = userEvent.setup();

    const about = await screen.findByRole("region", { name: "What was reported" });
    expect(within(about).getByRole("link", { name: "Easy money" })).toHaveAttribute(
      "href",
      "/opportunities/opp-1",
    );
    expect(within(about).getByText("Asks for money to apply.")).toBeVisible();
    const decide = screen.getByRole("region", { name: "Decide" });
    expect(within(decide).getByText(/settles the other 2 waiting/)).toBeVisible();
    const act = within(decide).getByRole("button", { name: "Take action" });
    expect(act).toBeDisabled();

    await user.selectOptions(within(decide).getByLabelText("What to do"), "HIDE");
    await user.type(within(decide).getByLabelText("Reason"), "Asks applicants for a fee.");
    await user.click(act);

    // Hiding can be undone, so it is not second-guessed with a question.
    expect(window.confirm).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(api.last(`POST ${ONE}resolve/`)?.body).toEqual({
        action: "HIDE",
        reason: "Asks applicants for a fee.",
        until: null,
      }),
    );
    // Decided: the choices go, the history shows what was done, and there is a way on to
    // where it can be put back.
    await waitFor(() => expect(screen.queryByRole("region", { name: "Decide" })).toBeNull());
    const history = screen.getByRole("region", { name: "What moderators have done to it" });
    expect(history).toHaveTextContent("Hidden by Grace Hopper");
    expect(
      within(history).getByRole("link", { name: "Moderate this opportunity" }),
    ).toHaveAttribute("href", "/moderation/targets/OPPORTUNITY/opp-1");
  });

  it("asks before removing for good, and does nothing if that is declined", async () => {
    vi.mocked(window.confirm).mockReturnValue(false);
    const api = mockApi({ [`GET ${ONE}`]: () => json(report()) });
    renderApp("/moderation/reports/r-1", MODERATOR);
    const user = userEvent.setup();

    await user.selectOptions(await screen.findByLabelText("What to do"), "REMOVE");
    await user.type(screen.getByLabelText("Reason"), "Fraud.");
    await user.click(screen.getByRole("button", { name: "Take action" }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("cannot be undone"));
    expect(api.count(`POST ${ONE}resolve/`)).toBe(0);
  });

  it("claims and dismisses", async () => {
    let current = report();
    const becomes = (next: ReportDetail) => () => {
      current = next;
      return json(next);
    };
    const api = mockApi({
      [`GET ${ONE}`]: () => json(current),
      [`POST ${ONE}claim/`]: becomes(report({ status: "UNDER_REVIEW", assigned_to: grace })),
      [`POST ${ONE}dismiss/`]: becomes(
        report({ status: "DISMISSED", available_actions: [], resolution_note: "Fine." }),
      ),
      [QUEUE]: () => page([]),
    });
    renderApp("/moderation/reports/r-1", MODERATOR);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Take this report" }));
    expect(await screen.findByText("Under review")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Take this report" })).toBeNull();

    await user.type(screen.getByLabelText(/Note for other moderators/), "Fine.");
    await user.click(screen.getByRole("button", { name: "No action needed" }));

    await waitFor(() => expect(api.last(`POST ${ONE}dismiss/`)?.body).toEqual({ note: "Fine." }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Decide" })).toBeNull());
    expect(screen.getByText("Fine.")).toBeVisible();
  });

  it("offers only dismissing where nothing can be done, and says why a decision failed", async () => {
    mockApi({
      [`GET ${ONE}`]: () =>
        json(
          report({
            available_actions: [],
            target: { type: "USER", id: "u-9", name: "Mallory", url: "/users/u-9" },
          }),
        ),
      [`POST ${ONE}dismiss/`]: () =>
        apiError(403, "permission_denied", "You do not have permission to perform this action."),
      [QUEUE]: () => page([]),
    });
    renderApp("/moderation/reports/r-1", MODERATOR);
    const user = userEvent.setup();

    expect(await screen.findByText(/Nothing can be done to this person from here/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Take action" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "No action needed" }));
    expect(await screen.findByText(/do not have permission/)).toBeVisible();
  });
});

describe("moderating something directly", () => {
  const ACT = "POST /api/v1/moderation/actions/";
  const done = (
    action_type: ModerationAction["action_type"],
    reason: string,
  ): ModerationAction => ({
    id: `a-${action_type}`,
    action_type,
    reason,
    expires_at: null,
    actor: grace,
    created_at: "2026-10-11T09:00:00Z",
  });
  const view = (overrides: Partial<TargetDetail> = {}): TargetDetail => ({
    target,
    standing: [],
    possible_actions: [],
    timed_actions: [],
    actions: [],
    ...overrides,
  });

  it("shows how something stands and restores what was hidden", async () => {
    const hide = done("HIDE", "Fee.");
    let current = view({
      standing: ["Hidden"],
      possible_actions: ["REMOVE", "RESTORE"],
      actions: [hide],
    });
    const api = mockApi({
      "GET /api/v1/moderation/targets/OPPORTUNITY/opp-1/": () => json(current),
      [ACT]: () => {
        const restore = done("RESTORE", "Poster fixed it.");
        current = view({ possible_actions: ["HIDE", "REMOVE"], actions: [restore, hide] });
        return json(restore, 201);
      },
    });
    renderApp("/moderation/targets/OPPORTUNITY/opp-1", MODERATOR);
    const user = userEvent.setup();

    expect(await screen.findByRole("heading", { name: "Moderate opportunity" })).toBeVisible();
    expect(
      within(screen.getByRole("list", { name: "How it stands" })).getByText("Hidden"),
    ).toBeVisible();
    await user.selectOptions(screen.getByLabelText("What to do"), "RESTORE");
    // Putting something back has no end date to ask for.
    expect(screen.queryByLabelText("Until (optional)")).toBeNull();
    await user.type(screen.getByLabelText("Reason"), "Poster fixed it.");
    await user.click(screen.getByRole("button", { name: "Take action" }));

    await waitFor(() =>
      expect(api.last(ACT)?.body).toEqual({
        target_type: "OPPORTUNITY",
        target_id: "opp-1",
        action: "RESTORE",
        reason: "Poster fixed it.",
        until: null,
      }),
    );
    expect(await screen.findByText(/Nothing is in force/)).toBeVisible();
    const history = screen.getByRole("region", { name: "What moderators have done" });
    expect(within(history).getAllByRole("listitem")[0]).toHaveTextContent(
      "Restored by Grace Hopper",
    );
    // The form starts afresh for whatever is possible now.
    expect(screen.getByLabelText("Reason")).toHaveValue("");
  });

  it("suspends a person until a date, after asking", async () => {
    const person = { type: "USER" as const, id: "u-9", name: "Mallory", url: "/users/u-9" };
    const api = mockApi({
      "GET /api/v1/moderation/targets/USER/u-9/": () =>
        json(
          view({
            target: person,
            possible_actions: ["RESTRICT_POSTING", "SUSPEND", "WARN"],
            timed_actions: ["RESTRICT_POSTING", "SUSPEND"],
          }),
        ),
      [ACT]: () => json(done("SUSPEND", "Fraud."), 201),
    });
    renderApp("/moderation/targets/USER/u-9", makeSession(makeMe({ platform_role: "ADMIN" })));
    const user = userEvent.setup();

    await user.selectOptions(await screen.findByLabelText("What to do"), "WARN");
    expect(screen.queryByLabelText("Until (optional)")).toBeNull();
    await user.selectOptions(screen.getByLabelText("What to do"), "SUSPEND");
    const until = screen.getByLabelText("Until (optional)");
    await user.type(until, "2030-01-15");
    await user.type(screen.getByLabelText("Reason"), "Fraud.");
    expect(screen.getByText(/The person is shown this/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Take action" }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("signed out everywhere"));
    await waitFor(() => expect(api.count(ACT)).toBe(1));
    const sent = api.last(ACT)?.body as { action: string; until: string; target_type: string };
    expect([sent.target_type, sent.action]).toEqual(["USER", "SUSPEND"]);
    // The end of the chosen day, as an instant.
    expect(new Date(sent.until).toISOString()).toBe(sent.until);
    expect(new Date(sent.until).getTime()).toBeGreaterThan(
      new Date("2030-01-15T00:00:00").getTime(),
    );
    expect(new Date(sent.until).getTime()).toBeLessThan(new Date("2030-01-16T00:00:00").getTime());
  });

  it("says when there is nothing the viewer can do, and why an action was refused", async () => {
    mockApi({
      "GET /api/v1/moderation/targets/USER/u-9/": () =>
        json(view({ target: { ...target, type: "USER", url: "/users/u-9" } })),
    });
    renderApp("/moderation/targets/USER/u-9", MODERATOR);
    expect(await screen.findByText(/nothing you can do to this person/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Take action" })).toBeNull();

    cleanup();
    vi.unstubAllGlobals();
    mockApi({
      "GET /api/v1/moderation/targets/OPPORTUNITY/opp-1/": () =>
        json(view({ possible_actions: ["HIDE"] })),
      [ACT]: () => apiError(409, "action_not_possible", "This cannot be done as things now stand."),
    });
    renderApp("/moderation/targets/OPPORTUNITY/opp-1", MODERATOR);
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("What to do"), "HIDE");
    await user.type(screen.getByLabelText("Reason"), "Scam.");
    await user.click(screen.getByRole("button", { name: "Take action" }));
    expect(await screen.findByText("This cannot be done as things now stand.")).toBeVisible();
  });

  it("is linked from the page of what is moderated, for staff only", async () => {
    const JOB = "GET /api/v1/opportunities/opp-1/";
    mockApi({ [JOB]: () => json(job()) });
    renderApp("/opportunities/opp-1", MODERATOR);
    expect(await screen.findByRole("link", { name: "Moderate this job" })).toHaveAttribute(
      "href",
      "/moderation/targets/OPPORTUNITY/opp-1",
    );

    cleanup();
    vi.unstubAllGlobals();
    mockApi({ [JOB]: () => json(job()) });
    renderApp("/opportunities/opp-1", makeSession());
    await screen.findByRole("button", { name: "Report this job" });
    expect(screen.queryByRole("link", { name: /Moderate this/ })).toBeNull();
  });
});
