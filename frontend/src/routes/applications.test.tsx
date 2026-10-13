import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  Application,
  ApplicationDetail,
  ApplicationStatus,
  ApplicationStep,
} from "../features/applications/types";
import type { OpportunityDetail } from "../features/opportunities/types";
import { makeMe, makeSession, makeViewer } from "../test/fixtures";
import { apiError, json, mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const JOB = "GET /api/v1/opportunities/opp-1/";
const APPLY = "POST /api/v1/jobs/opp-1/apply/";
const LIST = "GET /api/v1/applications/";
const ONE = "/api/v1/applications/app-1/";
const page = <T,>(results: T[]) => json({ results, next: null, previous: null });

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
    event: null,
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
    viewer: makeViewer({ can_apply: true }),
    ...overrides,
  };
}

type Viewer = ApplicationDetail["viewer"];

/** As the applicant sees their own open application, unless told otherwise. */
const viewer = (overrides: Partial<Viewer> = {}): Viewer => ({
  is_applicant: true,
  can_manage: false,
  can_withdraw: true,
  can_download_resume: true,
  next_statuses: [],
  ...overrides,
});
const MANAGER = viewer({ is_applicant: false, can_manage: true, can_withdraw: false });

const step = (
  from_status: ApplicationStep["from_status"],
  to_status: ApplicationStatus,
  created_at: string,
  extra: Partial<ApplicationStep> = {},
): ApplicationStep => ({ from_status, to_status, created_at, note: "", actor: null, ...extra });

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
    referrals: [],
    history: [step("", "APPLIED", "2026-10-10T09:00:00Z")],
    viewer: viewer(),
    ...overrides,
  };
}

const resume = (name = "resume.pdf", type = "application/pdf", size = 20) =>
  new File([new Uint8Array(size)], name, { type });

beforeEach(() => vi.spyOn(window, "confirm").mockReturnValue(true));
afterEach(() => vi.unstubAllGlobals());

describe("applying from the job page", () => {
  it("sends the resume and note, then shows the application instead of the form", async () => {
    let applied = false;
    const api = mockApi({
      [JOB]: () =>
        json(
          job({
            viewer: applied
              ? makeViewer({ application: { id: "app-1", status: "APPLIED" } })
              : makeViewer({ can_apply: true }),
          }),
        ),
      [APPLY]: () => {
        applied = true;
        return json(application(), 201);
      },
    });
    renderApp("/opportunities/opp-1", makeSession());
    const user = userEvent.setup();

    const section = await screen.findByRole("region", { name: "Apply" });
    await user.upload(within(section).getByLabelText("Resume (PDF)"), resume());
    await user.type(
      within(section).getByLabelText("Note to the employer (optional)"),
      "  I have run Django in production.  ",
    );
    await user.click(within(section).getByRole("button", { name: "Send application" }));

    const mine = await screen.findByRole("region", { name: "Your application" });
    expect(within(mine).getByText("You have applied to this job.")).toBeVisible();
    expect(within(mine).getByText("Applied")).toBeVisible();
    expect(within(mine).getByRole("link", { name: "View your application" })).toHaveAttribute(
      "href",
      "/applications/app-1",
    );
    expect(screen.queryByRole("button", { name: "Send application" })).toBeNull();

    const sent = api.last(APPLY)?.body as FormData;
    expect((sent.get("resume") as File).name).toBe("resume.pdf");
    expect(sent.get("cover_note")).toBe("I have run Django in production.");
    // The browser sets the multipart boundary itself.
    expect(api.last(APPLY)?.headers["Content-Type"]).toBeUndefined();
    expect(api.count(APPLY)).toBe(1);
  });

  it("checks the file before uploading anything", async () => {
    const api = mockApi({ [JOB]: () => json(job()) });
    renderApp("/opportunities/opp-1", makeSession());
    // Without this the test would be stopped by the input's own "accept" filter.
    const user = userEvent.setup({ applyAccept: false });
    const input = await screen.findByLabelText("Resume (PDF)");
    const submit = screen.getByRole("button", { name: "Send application" });

    await user.click(submit);
    expect(await screen.findByText("Attach your resume as a PDF.")).toBeVisible();
    expect(input).toBeInvalid();

    await user.upload(input, resume("resume.docx", "application/msword"));
    expect(await screen.findByText("The resume must be a PDF file.")).toBeVisible();

    await user.upload(input, resume("big.pdf", "application/pdf", 5 * 1024 * 1024 + 1));
    expect(await screen.findByText("The resume must be 5 MB or smaller.")).toBeVisible();
    await user.click(submit);

    expect(api.count(APPLY)).toBe(0);

    await user.upload(input, resume());
    expect(screen.queryByText(/The resume must be/)).toBeNull();
    expect(input).toBeValid();
  });

  it("shows what the server says about the file next to the file", async () => {
    mockApi({
      [JOB]: () => json(job()),
      [APPLY]: () =>
        apiError(422, "invalid_file", "The resume must be a PDF file.", {
          resume: ["The resume must be a PDF file."],
        }),
    });
    renderApp("/opportunities/opp-1", makeSession());
    const user = userEvent.setup();

    await user.upload(await screen.findByLabelText("Resume (PDF)"), resume());
    await user.click(screen.getByRole("button", { name: "Send application" }));

    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]).toHaveTextContent("The resume must be a PDF file.");
    expect(screen.getByLabelText("Resume (PDF)")).toBeInvalid();
  });

  it("says so when the job stopped taking applications in the meantime", async () => {
    mockApi({
      [JOB]: () => json(job()),
      [APPLY]: () => apiError(409, "not_accepting", "This job is no longer taking applications."),
    });
    renderApp("/opportunities/opp-1", makeSession());
    const user = userEvent.setup();

    await user.upload(await screen.findByLabelText("Resume (PDF)"), resume());
    await user.click(screen.getByRole("button", { name: "Send application" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This job is no longer taking applications.",
    );
    expect(screen.getByRole("button", { name: "Send application" })).toBeEnabled();
  });

  it("asks a visitor to sign in, and comes back to the job afterwards", async () => {
    const api = mockApi({ [JOB]: () => json(job({ viewer: makeViewer() })) });
    renderApp("/opportunities/opp-1");

    const link = await screen.findByRole("link", { name: "Sign in to apply" });

    expect(link).toHaveAttribute("href", "/login?next=%2Fopportunities%2Fopp-1");
    expect(screen.queryByLabelText("Resume (PDF)")).toBeNull();
    expect(api.count(APPLY)).toBe(0);
  });

  it("asks someone who has not confirmed their email to do that first", async () => {
    mockApi({ [JOB]: () => json(job()) });
    renderApp("/opportunities/opp-1", makeSession(makeMe({ email_verified: false })));

    const section = await screen.findByRole("region", { name: "Apply" });

    expect(within(section).getByRole("alert")).toHaveTextContent(
      "Confirm your email address before applying.",
    );
    expect(screen.queryByLabelText("Resume (PDF)")).toBeNull();
  });

  it("offers nothing where there is nothing to apply to", async () => {
    const cases: Partial<OpportunityDetail>[] = [
      // The viewer manages the job.
      { viewer: makeViewer({ can_manage: true, editable_fields: [] }) },
      // Closed, and they never applied.
      { status: "CLOSED", close_reason: "FILLED", viewer: makeViewer() },
    ];
    for (const overrides of cases) {
      mockApi({
        [JOB]: () => json(job(overrides)),
        "GET /api/v1/opportunities/opp-1/communities/": () => json([]),
      });
      renderApp("/opportunities/opp-1", makeSession());

      expect(await screen.findByRole("heading", { name: "About the job" })).toBeVisible();
      expect(screen.queryByRole("region", { name: "Apply" })).toBeNull();
      expect(screen.queryByRole("region", { name: "Your application" })).toBeNull();
      cleanup();
      vi.unstubAllGlobals();
    }
  });

  it("still shows an earlier application on a job that has since closed", async () => {
    mockApi({
      [JOB]: () =>
        json(
          job({
            status: "CLOSED",
            close_reason: "FILLED",
            viewer: makeViewer({ application: { id: "app-1", status: "REJECTED" } }),
          }),
        ),
    });
    renderApp("/opportunities/opp-1", makeSession());

    const mine = await screen.findByRole("region", { name: "Your application" });

    expect(within(mine).getByText("Not selected")).toBeVisible();
  });
});

describe("my applications", () => {
  const rows: Application[] = [
    application(),
    application({
      id: "app-2",
      status: "INTERVIEW",
      status_changed_at: "2026-10-12T09:00:00Z",
      opportunity: {
        id: "opp-2",
        title: "Data Analyst",
        status: "CLOSED",
        organization: null,
      },
    }),
  ];

  it("lists them with where each stands, and filters through the address", async () => {
    const api = mockApi({
      [LIST]: ({ url }) =>
        page(rows.filter((row) => !url.searchParams.get("status") || row.status === "INTERVIEW")),
    });
    const router = renderApp("/applications", makeSession());
    const user = userEvent.setup();

    const list = await screen.findByRole("region", { name: "Your applications" });
    const items = await within(list).findAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Backend Engineer");
    expect(items[0]).toHaveTextContent("Example Labs · applied Oct 10, 2026");
    expect(items[0]).toHaveTextContent("Applied");
    expect(within(items[0]!).getByRole("link")).toHaveAttribute("href", "/applications/app-1");
    expect(items[1]).toHaveTextContent("updated Oct 12, 2026");
    expect(items[1]).toHaveTextContent("Interview");

    await user.selectOptions(screen.getByLabelText("Show"), "Interview");

    await waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(1));
    expect(router.state.location.search).toBe("?status=INTERVIEW");
    expect(api.last(LIST)?.url.searchParams.get("status")).toBe("INTERVIEW");
  });

  it("has empty, error and signed-out states", async () => {
    let failing = false;
    mockApi({
      [LIST]: () => (failing ? apiError(403, "forbidden", "Not allowed.") : page([])),
    });
    renderApp("/applications?status=HIRED", makeSession());
    expect(await screen.findByText("Nothing with the status “Hired”.")).toBeVisible();

    cleanup();
    renderApp("/applications", makeSession());
    expect(await screen.findByText(/You have not applied to anything yet/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Browse jobs" })).toHaveAttribute(
      "href",
      "/opportunities",
    );

    failing = true;
    cleanup();
    renderApp("/applications?status=OFFER", makeSession());
    expect(await screen.findByRole("alert")).toHaveTextContent("Not allowed.");

    cleanup();
    const router = renderApp("/applications");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(router.state.location.search).toBe("?next=%2Fapplications");
  });

  it("is linked from the header", async () => {
    mockApi({ [LIST]: () => page([]) });
    renderApp("/applications", makeSession());

    expect(await screen.findByRole("link", { name: "My applications" })).toHaveAttribute(
      "href",
      "/applications",
    );
  });
});

describe("one application", () => {
  it("shows the applicant their application and its history", async () => {
    mockApi({
      [`GET ${ONE}`]: () =>
        json(
          application({
            status: "INTERVIEW",
            history: [
              step("", "APPLIED", "2026-10-10T09:00:00Z"),
              step("APPLIED", "INTERVIEW", "2026-10-12T09:00:00Z"),
            ],
          }),
        ),
    });
    renderApp("/applications/app-1", makeSession());

    expect(await screen.findByRole("heading", { name: "Your application" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Backend Engineer" })).toHaveAttribute(
      "href",
      "/opportunities/opp-1",
    );
    expect(screen.getByText("I have run Django in production.")).toBeVisible();
    const history = within(screen.getByRole("region", { name: "History" })).getAllByRole(
      "listitem",
    );
    expect(history.map((item) => item.textContent)).toEqual([
      expect.stringContaining("Application sent"),
      expect.stringContaining("Moved to Interview"),
    ]);
    // Their own name and profile link would be noise on their own application.
    const details = screen.getByRole("region", { name: "Application" });
    expect(within(details).queryByRole("link", { name: /Ada Lovelace/ })).toBeNull();
  });

  it("withdraws after confirmation", async () => {
    const api = mockApi({
      [`GET ${ONE}`]: () => json(application()),
      [`POST ${ONE}withdraw/`]: () =>
        json(
          application({
            status: "WITHDRAWN",
            history: [
              step("", "APPLIED", "2026-10-10T09:00:00Z"),
              step("APPLIED", "WITHDRAWN", "2026-10-11T09:00:00Z"),
            ],
            viewer: viewer({ can_withdraw: false }),
          }),
        ),
    });
    renderApp("/applications/app-1", makeSession());
    const user = userEvent.setup();
    const button = await screen.findByRole("button", { name: "Withdraw application" });

    vi.mocked(window.confirm).mockReturnValueOnce(false);
    await user.click(button);
    expect(api.count(`POST ${ONE}withdraw/`)).toBe(0);

    await user.click(button);

    expect(await screen.findByText("Withdrawn by the applicant")).toBeVisible();
    expect(window.confirm).toHaveBeenLastCalledWith(
      expect.stringContaining("cannot apply to this job again"),
    );
    expect(screen.queryByRole("button", { name: "Withdraw application" })).toBeNull();
    expect(screen.getByRole("button", { name: "Download resume" })).toBeVisible();
    expect(api.count(`POST ${ONE}withdraw/`)).toBe(1);
  });

  it("downloads the resume through a link requested at the moment of the click", async () => {
    const followed: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      followed.push(this.getAttribute("href") ?? "");
    });
    const api = mockApi({
      [`GET ${ONE}`]: () => json(application()),
      [`GET ${ONE}resume/`]: () => json({ url: "/api/v1/files/signed-token/", expires_in: 60 }),
    });
    renderApp("/applications/app-1", makeSession());

    await userEvent.setup().click(await screen.findByRole("button", { name: "Download resume" }));

    await waitFor(() => expect(followed).toEqual(["/api/v1/files/signed-token/"]));
    expect(api.count(`GET ${ONE}resume/`)).toBe(1);
  });

  it("shows someone who manages the job who applied, without the applicant's controls", async () => {
    mockApi({
      [`GET ${ONE}`]: () => json(application({ viewer: MANAGER })),
    });
    renderApp("/applications/app-1", makeSession(makeMe({ id: "u-9" })));

    expect(
      await screen.findByRole("heading", { name: "Application from Ada Lovelace" }),
    ).toBeVisible();
    const details = screen.getByRole("region", { name: "Application" });
    expect(within(details).getByRole("link", { name: /Ada Lovelace/ })).toHaveAttribute(
      "href",
      "/users/u-1",
    );
    expect(screen.getByText(/Python developer/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Download resume" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Withdraw application" })).toBeNull();
  });

  it("explains a withdrawn application to the employer, and one that cannot be opened", async () => {
    mockApi({
      [`GET ${ONE}`]: () =>
        json(
          application({
            status: "WITHDRAWN",
            cover_note: "",
            viewer: { ...MANAGER, can_download_resume: false },
          }),
        ),
    });
    renderApp("/applications/app-1", makeSession());

    expect(await screen.findByText(/the resume is no longer available/)).toBeVisible();
    expect(screen.getByText("No note was included.")).toBeVisible();
    expect(within(screen.getByRole("main")).queryByRole("button")).toBeNull();

    cleanup();
    vi.unstubAllGlobals();
    mockApi({});
    renderApp("/applications/app-404", makeSession());
    expect(await screen.findByRole("heading", { name: "Application not found" })).toBeVisible();
  });
});
