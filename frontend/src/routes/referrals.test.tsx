import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ApplicationDetail, PipelineApplication } from "../features/applications/types";
import type { OpportunityDetail } from "../features/opportunities/types";
import type {
  ApplicationReferral,
  Referral,
  ReferralDetail,
  ReferralStatus,
} from "../features/referrals/types";
import { makeMe, makeSession, makeViewer } from "../test/fixtures";
import { apiError, json, mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const JOB = "GET /api/v1/opportunities/opp-1/";
const ELIGIBLE = "GET /api/v1/jobs/opp-1/eligible-referrers/";
const ASK = "POST /api/v1/jobs/opp-1/referral-requests/";
const LIST = "GET /api/v1/referrals/requests/";
const ONE = "/api/v1/referrals/requests/ref-1/";
const page = <T,>(results: T[]) => json({ results, next: null, previous: null });

const GRACE = {
  id: "u-2",
  display_name: "Grace Hopper",
  headline: "Compiler engineer",
  avatar_url: null,
};
const ADA = { id: "u-1", display_name: "Ada Lovelace", headline: "", avatar_url: null };
const NOTE = "I worked with Ada for two years and would hire her again.";

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
      openings: 1,
    },
    viewer: makeViewer({ can_apply: true, can_request_referral: true }),
    ...overrides,
  };
}

function referral(status: ReferralStatus = "REQUESTED"): Referral {
  return {
    id: "ref-1",
    status,
    created_at: "2026-10-10T09:00:00Z",
    status_changed_at: "2026-10-10T09:00:00Z",
    expires_at: "2026-10-24T09:00:00Z",
    opportunity: {
      id: "opp-1",
      title: "Backend Engineer",
      status: "PUBLISHED",
      organization: { id: "org-1", name: "Example Labs" },
    },
    requester: ADA,
    referrer: GRACE,
  };
}

type Viewer = ReferralDetail["viewer"];
const AS_REQUESTER: Viewer = { is_requester: true, is_referrer: false, actions: ["cancel"] };
const AS_REFERRER: Viewer = {
  is_requester: false,
  is_referrer: true,
  actions: ["accept", "decline"],
};

function detail(
  status: ReferralStatus,
  viewer: Viewer,
  overrides: Partial<ReferralDetail> = {},
): ReferralDetail {
  return {
    ...referral(status),
    message: "We worked together at Example Labs.",
    endorsement_note: "",
    referred_at: null,
    application_id: null,
    history: [{ from_status: "", to_status: "REQUESTED", created_at: "2026-10-10T09:00:00Z" }],
    viewer,
    ...overrides,
  };
}

beforeEach(() => vi.spyOn(window, "confirm").mockReturnValue(true));
afterEach(() => vi.unstubAllGlobals());

describe("asking for a referral from the job page", () => {
  it("lets the viewer pick one of their connections and send a request", async () => {
    let sent: Referral[] = [];
    const api = mockApi({
      [JOB]: () => json(job()),
      [LIST]: () => page(sent),
      [ELIGIBLE]: () => json({ referrers: sent.length ? [] : [GRACE], remaining: 3 }),
      [ASK]: () => {
        sent = [referral()];
        return json(detail("REQUESTED", AS_REQUESTER), 201);
      },
    });
    renderApp("/opportunities/opp-1", makeSession());

    const panel = await screen.findByRole("region", { name: "Referral" });
    // Nobody's name is fetched until the viewer asks to choose.
    expect(api.count(ELIGIBLE)).toBe(0);
    await userEvent.click(within(panel).getByRole("button", { name: "Ask for a referral" }));
    const send = await within(panel).findByRole("button", { name: "Send request" });
    expect(send).toBeDisabled();

    await userEvent.click(within(panel).getByRole("radio", { name: /Grace Hopper/ }));
    await userEvent.type(
      within(panel).getByLabelText("Message to them (optional)"),
      "Would you refer me?",
    );
    await userEvent.click(send);

    expect(await within(panel).findByRole("link", { name: "Asked Grace Hopper" })).toHaveAttribute(
      "href",
      "/referrals/ref-1",
    );
    expect(within(panel).getByText("Requested")).toBeVisible();
    expect(api.last(ASK)?.body).toEqual({ referrer_id: "u-2", message: "Would you refer me?" });
    expect(within(panel).getByRole("button", { name: "Ask someone else" })).toBeVisible();
  });

  it("explains when none of the viewer's connections can be asked", async () => {
    mockApi({
      [JOB]: () => json(job()),
      [LIST]: () => page([]),
      [ELIGIBLE]: () => json({ referrers: [], remaining: 3 }),
    });
    renderApp("/opportunities/opp-1", makeSession());

    await userEvent.click(await screen.findByRole("button", { name: "Ask for a referral" }));

    expect(
      await screen.findByText(/None of your connections can be asked about this job/),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Your connections" })).toHaveAttribute(
      "href",
      "/connections",
    );
  });

  it("says why a request was refused", async () => {
    mockApi({
      [JOB]: () => json(job()),
      [LIST]: () => page([]),
      [ELIGIBLE]: () => json({ referrers: [GRACE], remaining: 1 }),
      [ASK]: () =>
        apiError(422, "not_eligible", "This person cannot be asked to refer you for this job."),
    });
    renderApp("/opportunities/opp-1", makeSession());

    await userEvent.click(await screen.findByRole("button", { name: "Ask for a referral" }));
    await userEvent.click(await screen.findByRole("radio", { name: /Grace Hopper/ }));
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot be asked to refer you/);
  });

  it("shows earlier requests but no way to ask when referrals are closed to the viewer", async () => {
    mockApi({
      [JOB]: () => json(job({ status: "CLOSED", viewer: makeViewer() })),
      [LIST]: () => page([referral("CLOSED")]),
    });
    renderApp("/opportunities/opp-1", makeSession());

    const panel = await screen.findByRole("region", { name: "Referral" });
    expect(within(panel).getByText("Closed")).toBeVisible();
    expect(within(panel).queryByRole("button")).not.toBeInTheDocument();
  });

  it("offers nothing to a visitor, or where referrals do not apply", async () => {
    mockApi({ [JOB]: () => json(job({ viewer: makeViewer() })), [LIST]: () => page([]) });
    renderApp("/opportunities/opp-1", makeSession());

    expect(await screen.findByRole("heading", { name: "Backend Engineer" })).toBeVisible();
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Referral" })).not.toBeInTheDocument(),
    );
  });

  it("asks an unverified viewer to confirm their email first", async () => {
    mockApi({ [JOB]: () => json(job()), [LIST]: () => page([]) });
    renderApp("/opportunities/opp-1", makeSession(makeMe({ email_verified: false })));

    const panel = await screen.findByRole("region", { name: "Referral" });
    expect(within(panel).getByText(/Confirm your email address to ask/)).toBeVisible();
    expect(within(panel).queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("referrals page", () => {
  it("lists what the viewer asked for, and what was asked of them", async () => {
    const api = mockApi({
      [LIST]: ({ url }) =>
        page(url.searchParams.get("role") === "referrer" ? [] : [referral("ACCEPTED")]),
    });
    const router = renderApp("/referrals", makeSession());

    const list = await screen.findByRole("region", { name: "Your referrals" });
    expect(await within(list).findByRole("link", { name: "Backend Engineer" })).toHaveAttribute(
      "href",
      "/referrals/ref-1",
    );
    expect(within(list).getByText(/Example Labs · asked Grace Hopper/)).toBeVisible();
    expect(within(list).getByText("Accepted")).toBeVisible();

    await userEvent.click(within(list).getByRole("link", { name: "Asked of me" }));

    expect(await within(list).findByText("Nobody has asked you for a referral.")).toBeVisible();
    expect(router.state.location.search).toBe("?show=received");
    expect(api.last(LIST)?.url.searchParams.get("role")).toBe("referrer");
  });

  it("offers to retry a list that failed to load", async () => {
    let fail = true;
    mockApi({
      [LIST]: () => (fail ? apiError(403, "forbidden", "Something broke.") : page([])),
    });
    renderApp("/referrals", makeSession());

    expect(await screen.findByRole("alert")).toHaveTextContent("Something broke.");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText(/You have not asked anyone for a referral yet/)).toBeVisible();
  });
});

describe("one referral", () => {
  it("lets the referrer accept, then make the referral with a note", async () => {
    let current = detail("REQUESTED", AS_REFERRER);
    const api = mockApi({
      [`GET ${ONE}`]: () => json(current),
      [`POST ${ONE}accept/`]: () => {
        current = detail("ACCEPTED", { ...AS_REFERRER, actions: ["refer", "back_out"] });
        return json(current);
      },
      [`POST ${ONE}refer/`]: () => {
        current = detail(
          "REFERRED",
          { ...AS_REFERRER, actions: [] },
          { endorsement_note: NOTE, referred_at: "2026-10-11T09:00:00Z" },
        );
        return json(current);
      },
    });
    renderApp("/referrals/ref-1", makeSession(makeMe({ id: "u-2" })));

    expect(
      await screen.findByRole("heading", { name: "Referral request from Ada Lovelace" }),
    ).toBeVisible();
    expect(screen.getByText("We worked together at Example Labs.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));

    const note = await screen.findByLabelText("Why you recommend Ada Lovelace");
    const make = screen.getByRole("button", { name: "Make the referral" });
    expect(make).toBeDisabled();
    await userEvent.type(note, NOTE);
    await userEvent.click(make);

    expect(
      await screen.findByRole("heading", { name: "What you told the people hiring" }),
    ).toBeVisible();
    expect(api.last(`POST ${ONE}refer/`)?.body).toEqual({ endorsement_note: NOTE });
    expect(screen.queryByRole("button", { name: "Make the referral" })).not.toBeInTheDocument();
  });

  it("lets the requester cancel after confirming, and follow their application", async () => {
    let current = detail("REQUESTED", AS_REQUESTER);
    const api = mockApi({
      [`GET ${ONE}`]: () => json(current),
      [`POST ${ONE}cancel/`]: () => {
        current = detail("CANCELLED", { ...AS_REQUESTER, actions: [] });
        return json(current);
      },
    });
    renderApp("/referrals/ref-1", makeSession());

    expect(
      await screen.findByRole("heading", { name: "Your referral request to Grace Hopper" }),
    ).toBeVisible();
    expect(screen.getByText(/Waiting for Grace Hopper to answer/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Cancel request" }));

    expect(window.confirm).toHaveBeenCalled();
    expect(await screen.findByText("Cancelled")).toBeVisible();
    expect(api.count(`POST ${ONE}cancel/`)).toBe(1);
    expect(screen.queryByRole("button", { name: "Cancel request" })).not.toBeInTheDocument();
  });

  it("shows the outcome and the application to the requester, without the note", async () => {
    mockApi({
      [`GET ${ONE}`]: () =>
        json(
          detail(
            "JOINED",
            { ...AS_REQUESTER, actions: [] },
            {
              application_id: "app-1",
              history: [
                { from_status: "", to_status: "REQUESTED", created_at: "2026-10-10T09:00:00Z" },
                {
                  from_status: "REQUESTED",
                  to_status: "REFERRED",
                  created_at: "2026-10-11T09:00:00Z",
                },
                {
                  from_status: "REFERRED",
                  to_status: "JOINED",
                  created_at: "2026-10-20T09:00:00Z",
                },
              ],
            },
          ),
        ),
    });
    renderApp("/referrals/ref-1", makeSession());

    expect(await screen.findByText("Joined")).toBeVisible();
    expect(screen.getByRole("link", { name: "View your application" })).toHaveAttribute(
      "href",
      "/applications/app-1",
    );
    const history = screen.getByRole("region", { name: "History" });
    expect(
      within(history)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      expect.stringContaining("Referral requested"),
      expect.stringContaining("Referral made"),
      expect.stringContaining("Hired"),
    ]);
    expect(screen.queryByRole("heading", { name: /says$/ })).not.toBeInTheDocument();
  });

  it("explains a referral that is missing or not the viewer's to see", async () => {
    mockApi({});
    renderApp("/referrals/ref-1", makeSession());

    expect(await screen.findByRole("heading", { name: "Referral not found" })).toBeVisible();
  });
});

describe("referrals in hiring", () => {
  const attached: ApplicationReferral = {
    id: "ref-1",
    referrer: GRACE,
    endorsement_note: NOTE,
    referred_at: "2026-10-11T09:00:00Z",
  };
  const row: PipelineApplication = {
    id: "app-1",
    status: "APPLIED",
    created_at: "2026-10-10T09:00:00Z",
    status_changed_at: "2026-10-10T09:00:00Z",
    headline: "Python developer",
    applicant: ADA,
    referrals: [attached],
    next_statuses: ["SCREENING", "REJECTED"],
  };

  it("marks a referred applicant in the pipeline", async () => {
    mockApi({
      [JOB]: () => json(job({ viewer: makeViewer({ can_manage: true }) })),
      "GET /api/v1/jobs/opp-1/applications/": () => page([row]),
      "GET /api/v1/jobs/opp-1/applications/summary/": () =>
        json({ counts: { APPLIED: 1 }, total: 1, openings: 1 }),
    });
    renderApp("/opportunities/opp-1/applications", makeSession(makeMe({ id: "u-9" })));

    expect(await screen.findByText("Referred")).toBeVisible();
    expect(screen.getByText("by Grace Hopper")).toBeVisible();
  });

  it("shows the people deciding what the referrer wrote", async () => {
    const application: ApplicationDetail = {
      id: "app-1",
      status: "APPLIED",
      created_at: "2026-10-10T09:00:00Z",
      status_changed_at: "2026-10-10T09:00:00Z",
      opportunity: referral().opportunity,
      cover_note: "",
      headline: "",
      applicant: ADA,
      referrals: [attached],
      history: [],
      viewer: {
        is_applicant: false,
        can_manage: true,
        can_withdraw: false,
        can_download_resume: true,
        next_statuses: ["SCREENING", "REJECTED"],
      },
    };
    mockApi({ "GET /api/v1/applications/app-1/": () => json(application) });
    renderApp("/applications/app-1", makeSession(makeMe({ id: "u-9" })));

    const section = await screen.findByRole("region", { name: "Referred by" });
    expect(within(section).getByRole("link", { name: /Grace Hopper/ })).toHaveAttribute(
      "href",
      "/users/u-2",
    );
    expect(within(section).getByText(NOTE)).toBeVisible();
  });
});
