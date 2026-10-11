import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ApplicationDetail,
  ApplicationStatus,
  PipelineApplication,
  PipelineSummary,
} from "../features/applications/types";
import type { OpportunityDetail } from "../features/opportunities/types";
import { FakeSocket } from "../test/fakeSocket";
import { makeMe, makeSession, makeViewer } from "../test/fixtures";
import { apiError, json, mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const JOB = "GET /api/v1/opportunities/opp-1/";
const LIST = "GET /api/v1/jobs/opp-1/applications/";
const SUMMARY = "GET /api/v1/jobs/opp-1/applications/summary/";
const ONE = "/api/v1/applications/app-1/";
const MOVE = `POST ${ONE}transition/`;
const page = <T,>(results: T[]) => json({ results, next: null, previous: null });

const AFTER_APPLIED: ApplicationStatus[] = [
  "SCREENING",
  "SHORTLISTED",
  "INTERVIEW",
  "OFFER",
  "HIRED",
  "REJECTED",
];

function job(overrides: Partial<OpportunityDetail> = {}): OpportunityDetail {
  return {
    id: "opp-1",
    type: "JOB",
    title: "Backend Engineer",
    description: "Build and run our Django services.",
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
    organization: {
      id: "org-1",
      name: "Example Labs",
      slug: "example-labs",
      verification_status: "VERIFIED",
    },
    posted_by: null,
    skills: [],
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
      openings: 2,
    },
    viewer: makeViewer({ can_manage: true, editable_fields: ["deadline", "description"] }),
    ...overrides,
  };
}

function row(
  id: string,
  name: string,
  status: ApplicationStatus = "APPLIED",
  nextStatuses: ApplicationStatus[] = AFTER_APPLIED,
): PipelineApplication {
  return {
    id,
    status,
    created_at: "2026-10-10T09:00:00Z",
    status_changed_at: "2026-10-10T09:00:00Z",
    headline: "Python developer",
    applicant: { id: `u-${id}`, display_name: name, headline: "", avatar_url: null },
    next_statuses: nextStatuses,
  };
}

function summary(counts: Partial<Record<ApplicationStatus, number>> = {}): PipelineSummary {
  const all = {
    APPLIED: 0,
    SCREENING: 0,
    SHORTLISTED: 0,
    INTERVIEW: 0,
    OFFER: 0,
    HIRED: 0,
    REJECTED: 0,
    WITHDRAWN: 0,
    ...counts,
  };
  return {
    counts: all,
    total: Object.values(all).reduce((sum, count) => sum + count, 0),
    openings: 2,
  };
}

function application(overrides: Partial<ApplicationDetail> = {}): ApplicationDetail {
  return {
    id: "app-1",
    status: "APPLIED",
    created_at: "2026-10-10T09:00:00Z",
    status_changed_at: "2026-10-10T09:00:00Z",
    opportunity: {
      id: "opp-1",
      title: "Backend Engineer",
      status: "PUBLISHED",
      organization: { id: "org-1", name: "Example Labs" },
    },
    cover_note: "I have run Django in production.",
    headline: "Python developer",
    applicant: { id: "u-1", display_name: "Ada Lovelace", headline: "", avatar_url: null },
    history: [
      {
        from_status: "",
        to_status: "APPLIED",
        created_at: "2026-10-10T09:00:00Z",
        note: "",
        actor: null,
      },
    ],
    viewer: {
      is_applicant: false,
      can_manage: true,
      can_withdraw: false,
      can_download_resume: true,
      next_statuses: AFTER_APPLIED,
    },
    ...overrides,
  };
}

const recruiter = () => makeSession(makeMe({ id: "u-9" }));

beforeEach(() => vi.spyOn(window, "confirm").mockReturnValue(true));
afterEach(() => vi.unstubAllGlobals());

describe("a job's applications", () => {
  it("lists the applicants with a count for every stage", async () => {
    const api = mockApi({
      [JOB]: () => json(job()),
      [SUMMARY]: () => json(summary({ APPLIED: 1, INTERVIEW: 1 })),
      [LIST]: ({ url }) =>
        page(
          [
            row("app-1", "Ada Lovelace"),
            row("app-2", "Grace Hopper", "INTERVIEW", ["OFFER", "HIRED", "REJECTED"]),
          ].filter((r) => !url.searchParams.get("status") || r.status === "INTERVIEW"),
        ),
    });
    const router = renderApp("/opportunities/opp-1/applications", recruiter());
    const user = userEvent.setup();

    const list = await screen.findByRole("region", { name: "Applications to this job" });
    const rows = await within(list).findAllByRole("listitem", { name: "" });
    const people = rows.filter((item) => within(item).queryByRole("combobox"));
    expect(people).toHaveLength(2);
    expect(people[0]).toHaveTextContent("Ada Lovelace");
    expect(people[0]).toHaveTextContent("Python developer · applied Oct 10, 2026");
    expect(within(people[0]!).getByRole("link", { name: /Ada Lovelace/ })).toHaveAttribute(
      "href",
      "/applications/app-1",
    );
    expect(screen.getByRole("link", { name: "Backend Engineer" })).toHaveAttribute(
      "href",
      "/opportunities/opp-1",
    );

    const stages = screen.getByRole("navigation", { name: "Stages" });
    expect(within(stages).getByRole("link", { name: "All (2)" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(stages).getByRole("link", { name: "Hired (0)" })).toBeVisible();
    // Each move offered is the server's list for that row, nothing more.
    expect(
      within(screen.getByLabelText("Move Grace Hopper to"))
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Move to…", "Offer", "Hired", "Reject"]);

    await user.click(within(stages).getByRole("link", { name: "Interview (1)" }));

    await waitFor(() => expect(within(list).queryByText("Ada Lovelace")).toBeNull());
    expect(router.state.location.search).toBe("?status=INTERVIEW");
    expect(api.last(LIST)?.url.searchParams.get("status")).toBe("INTERVIEW");
    expect(within(stages).getByRole("link", { name: "Interview (1)" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("moves an applicant from their row and refreshes the counts", async () => {
    let status: ApplicationStatus = "APPLIED";
    const api = mockApi({
      [JOB]: () => json(job()),
      [SUMMARY]: () => json(summary({ [status]: 1 })),
      [LIST]: () =>
        page([
          row(
            "app-1",
            "Ada Lovelace",
            status,
            status === "APPLIED" ? AFTER_APPLIED : ["OFFER", "HIRED", "REJECTED"],
          ),
        ]),
      [MOVE]: () => {
        status = "INTERVIEW";
        return json(application({ status }));
      },
    });
    renderApp("/opportunities/opp-1/applications", recruiter());
    const user = userEvent.setup();
    const update = await screen.findByRole("button", { name: "Update Ada Lovelace" });
    expect(update).toBeDisabled();

    await user.selectOptions(screen.getByLabelText("Move Ada Lovelace to"), "Interview");
    await user.click(update);

    expect(await screen.findByRole("link", { name: "Interview (1)" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Applied (0)" })).toBeVisible();
    // Says which status was on screen, so the server can refuse a move made on old news.
    expect(api.last(MOVE)?.body).toEqual({ to: "INTERVIEW", expected_status: "APPLIED", note: "" });
    expect(window.confirm).not.toHaveBeenCalled();
    expect(api.count(MOVE)).toBe(1);
  });

  it("asks before a decision that cannot be undone", async () => {
    const api = mockApi({
      [JOB]: () => json(job()),
      [SUMMARY]: () => json(summary({ APPLIED: 1 })),
      [LIST]: () => page([row("app-1", "Ada Lovelace")]),
      [MOVE]: () => json(application({ status: "REJECTED" })),
    });
    renderApp("/opportunities/opp-1/applications", recruiter());
    const user = userEvent.setup();
    const choice = await screen.findByLabelText("Move Ada Lovelace to");
    const update = screen.getByRole("button", { name: "Update Ada Lovelace" });

    vi.mocked(window.confirm).mockReturnValueOnce(false);
    await user.selectOptions(choice, "Reject");
    await user.click(update);
    expect(window.confirm).toHaveBeenLastCalledWith(
      "Reject Ada Lovelace's application? This cannot be undone.",
    );
    expect(api.count(MOVE)).toBe(0);

    await user.selectOptions(choice, "Hired");
    await user.click(update);
    expect(window.confirm).toHaveBeenLastCalledWith(
      "Mark Ada Lovelace as hired? This cannot be undone.",
    );
    await waitFor(() => expect(api.last(MOVE)?.body).toMatchObject({ to: "HIRED" }));
  });

  it("explains when a colleague got there first, and shows where things stand", async () => {
    let rejectedElsewhere = false;
    const api = mockApi({
      [JOB]: () => json(job()),
      [SUMMARY]: () => json(summary(rejectedElsewhere ? { REJECTED: 1 } : { APPLIED: 1 })),
      [LIST]: () =>
        page([
          rejectedElsewhere
            ? row("app-1", "Ada Lovelace", "REJECTED", [])
            : row("app-1", "Ada Lovelace"),
        ]),
      [MOVE]: () => {
        rejectedElsewhere = true;
        return apiError(409, "stale_state", "The resource changed since it was last read.");
      },
    });
    renderApp("/opportunities/opp-1/applications", recruiter());
    const user = userEvent.setup();

    await user.selectOptions(await screen.findByLabelText("Move Ada Lovelace to"), "Interview");
    await user.click(screen.getByRole("button", { name: "Update Ada Lovelace" }));

    // The row is refetched: it now shows the colleague's decision and offers no moves.
    expect(await screen.findByRole("link", { name: "Not selected (1)" })).toBeVisible();
    await waitFor(() => expect(screen.queryByLabelText("Move Ada Lovelace to")).toBeNull());
    expect(api.count(MOVE)).toBe(1);
  });

  it("says when the openings are filled, has an empty state, and refuses outsiders", async () => {
    mockApi({
      [JOB]: () => json(job()),
      [SUMMARY]: () => json(summary({ HIRED: 2 })),
      [LIST]: () => page([]),
    });
    renderApp("/opportunities/opp-1/applications?status=OFFER", recruiter());

    expect(await screen.findByText(/All 2 openings are filled/)).toBeVisible();
    expect(screen.getByRole("link", { name: "close it" })).toHaveAttribute(
      "href",
      "/opportunities/opp-1",
    );
    expect(await screen.findByText("No applications with the status “Offer”.")).toBeVisible();

    vi.unstubAllGlobals();
    mockApi({
      [JOB]: () => json(job({ viewer: makeViewer({ can_apply: true }) })),
      [SUMMARY]: () => apiError(403, "permission_denied", "You do not have permission."),
      [LIST]: () => apiError(403, "permission_denied", "You do not have permission."),
    });
    const { unmount } = { unmount: () => document.body.replaceChildren() };
    unmount();
    renderApp("/opportunities/opp-1/applications", recruiter());

    expect(
      await screen.findByRole("heading", { name: "Applications not available" }),
    ).toBeVisible();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("is reached from the job page by whoever manages the job", async () => {
    mockApi({
      [JOB]: () => json(job()),
      "GET /api/v1/opportunities/opp-1/communities/": () => json([]),
      "GET /api/v1/opportunities/opp-1/communities/options/": () => json([]),
    });
    renderApp("/opportunities/opp-1", recruiter());

    expect(await screen.findByRole("link", { name: "View applications" })).toHaveAttribute(
      "href",
      "/opportunities/opp-1/applications",
    );
  });
});

describe("deciding on one application", () => {
  it("moves it with a private note, and shows the team's notes in the history", async () => {
    const api = mockApi({
      [`GET ${ONE}`]: () => json(application()),
      [MOVE]: ({ body }) => {
        const sent = body as { note: string };
        return json(
          application({
            status: "INTERVIEW",
            history: [
              ...application().history,
              {
                from_status: "APPLIED",
                to_status: "INTERVIEW",
                created_at: "2026-10-12T09:00:00Z",
                note: sent.note,
                actor: { id: "u-9", display_name: "Rae Recruiter", headline: "", avatar_url: null },
              },
            ],
            viewer: {
              ...application().viewer,
              next_statuses: ["OFFER", "HIRED", "REJECTED"],
            },
          }),
        );
      },
    });
    renderApp("/applications/app-1", recruiter());
    const user = userEvent.setup();

    const decide = await screen.findByRole("region", { name: "Decide" });
    expect(within(decide).getByText(/The applicant never sees it/)).toBeVisible();
    await user.selectOptions(within(decide).getByLabelText("Move to"), "Interview");
    await user.type(
      within(decide).getByLabelText("Note for your team (optional)"),
      " Strong on SQL. ",
    );
    await user.click(within(decide).getByRole("button", { name: "Update" }));

    const history = await screen.findByRole("region", { name: "History" });
    expect(await within(history).findByText("Strong on SQL.")).toBeVisible();
    expect(within(history).getByText(/by Rae Recruiter/)).toBeVisible();
    expect(api.last(MOVE)?.body).toEqual({
      to: "INTERVIEW",
      expected_status: "APPLIED",
      note: "Strong on SQL.",
    });
    // Ready for the next move: cleared, and offering only what is now possible.
    expect(within(decide).getByLabelText("Note for your team (optional)")).toHaveValue("");
    expect(
      within(within(decide).getByLabelText("Move to"))
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Move to…", "Offer", "Hired", "Reject"]);
    expect(within(decide).getByRole("link", { name: /All applications/ })).toHaveAttribute(
      "href",
      "/opportunities/opp-1/applications",
    );
  });

  it("offers no move once it is decided, and no deciding at all to the applicant", async () => {
    mockApi({
      [`GET ${ONE}`]: () =>
        json(
          application({
            status: "HIRED",
            viewer: { ...application().viewer, next_statuses: [] },
          }),
        ),
    });
    renderApp("/applications/app-1", recruiter());

    const decide = await screen.findByRole("region", { name: "Decide" });
    expect(within(decide).getByText(/has been decided/)).toBeVisible();
    expect(within(decide).queryByRole("combobox")).toBeNull();

    vi.unstubAllGlobals();
    document.body.replaceChildren();
    mockApi({
      [`GET ${ONE}`]: () =>
        json(
          application({
            viewer: {
              is_applicant: true,
              can_manage: false,
              can_withdraw: true,
              can_download_resume: true,
              next_statuses: [],
            },
          }),
        ),
    });
    renderApp("/applications/app-1", makeSession());

    expect(await screen.findByRole("heading", { name: "Your application" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Decide" })).toBeNull();
  });
});

describe("the applicant's side, live", () => {
  it("shows the new status the moment the employer moves the application", async () => {
    let status: ApplicationStatus = "APPLIED";
    mockApi({
      "POST /api/v1/auth/ws-ticket/": () => json({ ticket: "t-1", expires_in: 30 }),
      "GET /api/v1/notifications/unread-count/": () => json({ count: 0 }),
      [`GET ${ONE}`]: () =>
        json(
          application({
            status,
            viewer: {
              is_applicant: true,
              can_manage: false,
              can_withdraw: true,
              can_download_resume: true,
              next_statuses: [],
            },
          }),
        ),
    });
    FakeSocket.install();
    renderApp("/applications/app-1", makeSession());
    await waitFor(() => expect(FakeSocket.opened).toHaveLength(1));
    act(() => FakeSocket.latest.hello());
    const heading = (await screen.findByRole("heading", { name: "Your application" }))
      .parentElement!;
    expect(within(heading).getByText("Applied")).toBeVisible();

    status = "INTERVIEW";
    act(() => FakeSocket.latest.event("application.updated", { id: "app-1", status }));

    expect(await within(heading).findByText("Interview")).toBeVisible();
  });
});
