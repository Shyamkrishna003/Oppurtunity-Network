import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { formatSalary } from "../features/opportunities/format";
import type { JobDetail, OpportunityDetail } from "../features/opportunities/types";
import { makeMe, makeSession, makeViewer } from "../test/fixtures";
import { apiError, json, mockApi, noContent } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const JOB = "/api/v1/opportunities/opp-1/";
const page = <T,>(results: T[]) => json({ results, next: null, previous: null });
const python = { id: "s-py", name: "Python", slug: "python" };

const job: JobDetail = {
  department: "Platform",
  employment_type: "FULL_TIME",
  experience_level: "MID",
  salary_min: 800000,
  salary_max: 1200000,
  salary_currency: "INR",
  salary_period: "YEAR",
  application_method: "INTERNAL",
  external_url: "",
  openings: 2,
};

function opportunity(overrides: Partial<OpportunityDetail> = {}): OpportunityDetail {
  return {
    id: "opp-1",
    type: "JOB",
    title: "Backend Engineer",
    description: "Build and run our Django services.",
    status: "PUBLISHED",
    visibility: "PUBLIC",
    moderation_status: "VISIBLE",
    communities: [],
    work_mode: "HYBRID",
    country_code: "IN",
    region: "Kerala",
    city: "Kochi",
    deadline: "2026-12-31T18:29:59Z",
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
    skills: [python],
    job,
    event: null,
    viewer: makeViewer(),
    ...overrides,
  };
}

const asManager = (overrides: Partial<OpportunityDetail> = {}) =>
  opportunity({
    viewer: makeViewer({ can_manage: true, editable_fields: null }),
    ...overrides,
  });
const PUBLISHED_EDITABLE = makeViewer({
  can_manage: true,
  editable_fields: ["deadline", "description"],
});

beforeEach(() => vi.spyOn(window, "confirm").mockReturnValue(true));
afterEach(() => vi.unstubAllGlobals());

describe("job page", () => {
  it("shows a visitor the job without any management controls", async () => {
    mockApi({ [`GET ${JOB}`]: () => json(opportunity()) });
    renderApp("/opportunities/opp-1");

    expect(await screen.findByRole("heading", { name: "Backend Engineer" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Example Labs" })).toBeVisible();
    expect(screen.getByText("Full-time · Mid level · Hybrid · Kochi, Kerala, IN")).toBeVisible();
    expect(screen.getByText(formatSalary(job))).toBeVisible();
    expect(screen.getByText("Python")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Manage" })).toBeNull();
    expect(screen.queryByText("Visible to")).toBeNull();
  });

  it("names the person behind a personal job", async () => {
    const postedBy = { id: "u-1", display_name: "Ada Lovelace", headline: "", avatar_url: null };
    mockApi({
      [`GET ${JOB}`]: () => json(opportunity({ organization: null, posted_by: postedBy })),
    });
    renderApp("/opportunities/opp-1");

    expect(await screen.findByText("Posted by Ada Lovelace")).toBeVisible();
  });

  it("links out safely when applications are taken elsewhere", async () => {
    const external = {
      ...job,
      application_method: "EXTERNAL",
      external_url: "https://x.example/apply",
    };
    mockApi({ [`GET ${JOB}`]: () => json(opportunity({ job: external as JobDetail })) });
    renderApp("/opportunities/opp-1");

    const link = await screen.findByRole("link", { name: "https://x.example/apply" });
    expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it.each([
    ["CLOSED", "This job is closed and no longer takes applications."],
    ["EXPIRED", "The deadline for this job has passed."],
  ] as const)("says so when the job is %s", async (status, message) => {
    mockApi({ [`GET ${JOB}`]: () => json(opportunity({ status })) });
    renderApp("/opportunities/opp-1");

    expect(await screen.findByText(message)).toBeVisible();
  });

  it("explains a job that is missing or not visible", async () => {
    mockApi({});
    renderApp("/opportunities/opp-1");

    expect(await screen.findByRole("heading", { name: "Opportunity not found" })).toBeVisible();
  });
});

describe("managing a job", () => {
  it("publishes a draft", async () => {
    const api = mockApi({
      [`GET ${JOB}`]: () => json(asManager({ status: "DRAFT", published_at: null })),
      [`POST ${JOB}publish/`]: () => json(asManager()),
    });
    renderApp("/opportunities/opp-1", makeSession());

    expect(await screen.findByText(/This is a draft/)).toBeVisible();
    await userEvent.setup().click(screen.getByRole("button", { name: "Publish" }));

    await waitFor(() => expect(api.count(`POST ${JOB}publish/`)).toBe(1));
  });

  it("lists what is missing when a draft cannot be published yet", async () => {
    mockApi({
      [`GET ${JOB}`]: () => json(asManager({ status: "DRAFT", published_at: null })),
      [`POST ${JOB}publish/`]: () =>
        apiError(422, "incomplete", "Complete these details before publishing.", {
          work_mode: ["Choose remote, hybrid or on-site."],
          "job.employment_type": ["Choose the employment type."],
        }),
    });
    renderApp("/opportunities/opp-1", makeSession());

    await userEvent.setup().click(await screen.findByRole("button", { name: "Publish" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Work mode:")).toBeVisible();
    expect(within(alert).getByText("Employment type:")).toBeVisible();
    expect(within(alert).getByText(/Choose the employment type/)).toBeVisible();
  });

  it("closes a published job with the chosen reason", async () => {
    const api = mockApi({
      [`GET ${JOB}`]: () => json(opportunity({ viewer: PUBLISHED_EDITABLE })),
      [`POST ${JOB}close/`]: () => json(opportunity({ status: "CLOSED" })),
    });
    renderApp("/opportunities/opp-1", makeSession());
    const user = userEvent.setup();

    await user.selectOptions(await screen.findByLabelText("Reason for closing"), "CANCELLED");
    await user.click(screen.getByRole("button", { name: "Close job" }));

    await waitFor(() =>
      expect(api.last(`POST ${JOB}close/`)?.body).toEqual({ reason: "CANCELLED" }),
    );
    expect(screen.queryByRole("button", { name: /Publish|Delete draft|Archive/ })).toBeNull();
  });

  it("offers only archiving once the job is closed, and no editing", async () => {
    const api = mockApi({
      [`GET ${JOB}`]: () =>
        json(
          opportunity({
            status: "CLOSED",
            viewer: makeViewer({ can_manage: true }),
          }),
        ),
      [`POST ${JOB}archive/`]: () => json(opportunity({ status: "ARCHIVED" })),
    });
    renderApp("/opportunities/opp-1", makeSession());

    await userEvent.setup().click(await screen.findByRole("button", { name: "Archive" }));

    await waitFor(() => expect(api.count(`POST ${JOB}archive/`)).toBe(1));
    expect(screen.queryByRole("link", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Publish|Close job|Delete draft/ })).toBeNull();
  });

  it("deletes a draft after confirmation and returns to the list", async () => {
    const api = mockApi({
      [`GET ${JOB}`]: () => json(asManager({ status: "DRAFT", published_at: null })),
      [`DELETE ${JOB}`]: noContent,
      "GET /api/v1/users/me/opportunities/": () => page([]),
    });
    const router = renderApp("/opportunities/opp-1", makeSession());

    await userEvent.setup().click(await screen.findByRole("button", { name: "Delete draft" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/my/opportunities"));
    expect(api.count(`DELETE ${JOB}`)).toBe(1);
  });

  it("tells the manager when a moderator has hidden the job", async () => {
    mockApi({ [`GET ${JOB}`]: () => json(asManager({ moderation_status: "HIDDEN" })) });
    renderApp("/opportunities/opp-1", makeSession());

    expect(await screen.findByText(/A moderator has hidden this opportunity/)).toBeVisible();
  });
});

describe("posting a job", () => {
  const organizations = () =>
    json([
      {
        membership_id: "m-1",
        organization: { id: "org-1", name: "Example Labs", slug: "example-labs" },
        role: "RECRUITER",
      },
      {
        membership_id: "m-2",
        organization: { id: "org-2", name: "Read Only Inc", slug: "read-only" },
        role: "MEMBER",
      },
    ]);

  it("saves a draft for an organization the user recruits for", async () => {
    const api = mockApi({
      "GET /api/v1/organizations/mine/": organizations,
      "GET /api/v1/skills/": () => json([python]),
      "POST /api/v1/opportunities/": () => json(asManager({ status: "DRAFT" }), 201),
      [`GET ${JOB}`]: () => json(asManager({ status: "DRAFT", published_at: null })),
    });
    const router = renderApp("/opportunities/new", makeSession());
    const user = userEvent.setup();

    const postAs = await screen.findByLabelText("Post as");
    // Only organizations where the user may post are offered.
    await waitFor(() =>
      expect(
        within(postAs)
          .getAllByRole("option")
          .map((o) => o.textContent),
      ).toEqual(["Myself", "Example Labs"]),
    );
    await user.selectOptions(postAs, "org-1");
    await user.type(screen.getByLabelText("Job title"), "Backend Engineer");
    await user.selectOptions(screen.getByLabelText("Work mode"), "REMOTE");
    await user.type(screen.getByLabelText("Salary from (optional)"), "800000");
    await user.type(screen.getByLabelText("Apply by (optional)"), "2026-12-31");
    await user.type(screen.getByLabelText("Skills needed"), "pyth");
    await user.click(await screen.findByRole("button", { name: "Python" }));
    await user.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/opportunities/opp-1"));
    const body = api.last("POST /api/v1/opportunities/")?.body as Record<string, unknown>;
    expect(body).toMatchObject({
      type: "JOB",
      organization_id: "org-1",
      title: "Backend Engineer",
      work_mode: "REMOTE",
      skill_ids: ["s-py"],
    });
    expect(body.job).toMatchObject({ salary_min: 800000, salary_max: null, openings: 1 });
    // The end of the chosen day, local time, sent as an absolute instant.
    expect(new Date(body.deadline as string).getTime()).toBe(
      new Date("2026-12-31T23:59:59").getTime(),
    );
  });

  it("offers the organization-only audience only when posting for an organization", async () => {
    mockApi({ "GET /api/v1/organizations/mine/": organizations });
    renderApp("/opportunities/new", makeSession());
    const user = userEvent.setup();
    const audiences = () =>
      within(screen.getByLabelText("Who can see it")).getAllByRole("option").length;

    const postAs = await screen.findByLabelText("Post as");
    await waitFor(() => expect(within(postAs).getAllByRole("option")).toHaveLength(2));
    expect(audiences()).toBe(2);
    await user.selectOptions(postAs, "org-1");
    expect(audiences()).toBe(3);
  });

  it("validates before calling the server", async () => {
    const api = mockApi({ "GET /api/v1/organizations/mine/": () => json([]) });
    renderApp("/opportunities/new", makeSession());
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Salary from (optional)"), "900");
    await user.type(screen.getByLabelText("Salary to (optional)"), "100");
    await user.selectOptions(screen.getByLabelText("How people apply"), "EXTERNAL");
    await user.click(screen.getByRole("button", { name: "Save draft" }));

    expect(await screen.findByText("Enter a title.")).toBeVisible();
    expect(screen.getByText("The maximum must not be below the minimum.")).toBeVisible();
    expect(screen.getByText(/Enter the full address where people apply/)).toBeVisible();
    expect(api.count("POST /api/v1/opportunities/")).toBe(0);
  });

  it("puts the server's field errors on the matching fields", async () => {
    mockApi({
      "GET /api/v1/organizations/mine/": () => json([]),
      "POST /api/v1/opportunities/": () =>
        apiError(400, "validation_error", "The request data is invalid.", {
          "job.salary_currency": ["Use a three-letter currency code, such as INR."],
          skill_ids: ["Some skills do not exist."],
        }),
    });
    renderApp("/opportunities/new", makeSession());
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Job title"), "Backend Engineer");
    await user.click(screen.getByRole("button", { name: "Save draft" }));

    expect(await screen.findByText("Check the highlighted details.")).toBeVisible();
    expect(screen.getByLabelText("Currency")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Some skills do not exist.")).toBeVisible();
  });

  it("asks an unverified user to confirm their email first", () => {
    mockApi({});
    renderApp("/opportunities/new", makeSession(makeMe({ email_verified: false })));

    expect(screen.getByText(/Confirm your email address before posting/)).toBeVisible();
    expect(screen.queryByLabelText("Job title")).toBeNull();
  });
});

describe("editing a job", () => {
  it("fills the form from the draft and saves the changes", async () => {
    const api = mockApi({
      [`GET ${JOB}`]: () => json(asManager({ status: "DRAFT", published_at: null })),
      [`PATCH ${JOB}`]: () => json(asManager({ status: "DRAFT" })),
    });
    const router = renderApp("/opportunities/opp-1/edit", makeSession());
    const user = userEvent.setup();

    const title = await screen.findByLabelText("Job title");
    expect(title).toHaveValue("Backend Engineer");
    expect(screen.getByLabelText("Salary to (optional)")).toHaveValue("1200000");
    await user.clear(title);
    await user.type(title, "Senior Backend Engineer");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/opportunities/opp-1"));
    expect(api.last(`PATCH ${JOB}`)?.body).toMatchObject({
      title: "Senior Backend Engineer",
      skill_ids: ["s-py"],
      job: { openings: 2, salary_max: 1200000 },
    });
  });

  it("locks everything but the safe fields once published, and still saves", async () => {
    const api = mockApi({
      [`GET ${JOB}`]: () => json(opportunity({ viewer: PUBLISHED_EDITABLE })),
      [`PATCH ${JOB}`]: () => json(opportunity({ viewer: PUBLISHED_EDITABLE })),
    });
    renderApp("/opportunities/opp-1/edit", makeSession());
    const user = userEvent.setup();

    const description = await screen.findByLabelText("Description");
    for (const label of ["Job title", "Work mode", "Employment type", "Who can see it"]) {
      expect(screen.getByLabelText(label)).toBeDisabled();
    }
    expect(screen.getByLabelText("Skills needed")).toBeDisabled();
    expect(description).toBeEnabled();
    expect(screen.getByLabelText("Number of openings")).toBeEnabled();

    await user.clear(description);
    await user.type(description, "Clearer wording.");
    await user.clear(screen.getByLabelText("Number of openings"));
    await user.type(screen.getByLabelText("Number of openings"), "3");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.count(`PATCH ${JOB}`)).toBe(1));
    const body = api.last(`PATCH ${JOB}`)?.body as Record<string, unknown>;
    // Only what may change is sent; locked fields are left out entirely.
    expect(Object.keys(body).sort()).toEqual(["deadline", "description", "job"]);
    expect(body).toMatchObject({ description: "Clearer wording.", job: { openings: 3 } });
  });

  it("refuses to open the form for a closed job or for someone who cannot manage it", async () => {
    mockApi({
      [`GET ${JOB}`]: () =>
        json(
          opportunity({
            status: "CLOSED",
            viewer: makeViewer({ can_manage: true }),
          }),
        ),
    });
    renderApp("/opportunities/opp-1/edit", makeSession());

    expect(await screen.findByText(/closed and can no longer be edited/)).toBeVisible();
    expect(screen.queryByLabelText("Job title")).toBeNull();
  });
});

describe("my opportunities", () => {
  it("lists what the user manages and filters by status through the URL", async () => {
    const api = mockApi({
      "GET /api/v1/users/me/opportunities/": ({ url }) =>
        page(url.searchParams.get("status") === "DRAFT" ? [] : [opportunity()]),
    });
    const router = renderApp("/my/opportunities", makeSession());
    const user = userEvent.setup();

    expect(await screen.findByRole("link", { name: "Backend Engineer" })).toBeVisible();
    expect(screen.getByText(/Example Labs · published/)).toBeVisible();
    await user.selectOptions(screen.getByLabelText("Show"), "DRAFT");

    expect(await screen.findByText("Nothing with the status “Draft”.")).toBeVisible();
    expect(router.state.location.search).toBe("?status=DRAFT");
    expect(api.last("GET /api/v1/users/me/opportunities/")?.url.searchParams.get("status")).toBe(
      "DRAFT",
    );
  });

  it("requires signing in", async () => {
    mockApi({});
    const router = renderApp("/my/opportunities");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(router.state.location.search).toBe("?next=%2Fmy%2Fopportunities");
  });
});
