import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { OpportunityDetail, OpportunityNumbers } from "../features/opportunities/types";
import { makeSession, makeViewer } from "../test/fixtures";
import { apiError, json, mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const JOB = "GET /api/v1/opportunities/opp-1/";
const NUMBERS = "GET /api/v1/opportunities/opp-1/stats/";

function job(overrides: Partial<OpportunityDetail> = {}): OpportunityDetail {
  return {
    id: "opp-1",
    type: "JOB",
    title: "Backend Engineer",
    description: "Build things.",
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
    posted_by: { id: "u-1", display_name: "Ada Lovelace", headline: "", avatar_url: null },
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
    viewer: makeViewer({ can_manage: true, editable_fields: ["description"] }),
    ...overrides,
  } as OpportunityDetail;
}

const numbers: OpportunityNumbers = {
  views: 1240,
  recent_views: 310,
  saves: 18,
  applications: 7,
  registrations: 0,
  referrals: 2,
  popularity_score: 409,
  views_by_day: Array.from({ length: 14 }, (_, index) => ({
    date: `2026-10-${String(index + 1).padStart(2, "0")}`,
    views: index === 13 ? 40 : index,
  })),
};

afterEach(() => vi.unstubAllGlobals());

describe("an opportunity's numbers", () => {
  it("shows its managers how it is doing, with the days as a table too", async () => {
    mockApi({ [JOB]: () => json(job()), [NUMBERS]: () => json(numbers) });
    renderApp("/opportunities/opp-1", makeSession());

    const card = await screen.findByRole("region", { name: "How it is doing" });
    const figure = (label: string) => within(card).getByText(label).nextElementSibling;
    expect(figure("People who opened it")).toHaveTextContent(new Intl.NumberFormat().format(1240));
    expect(figure("Applications")).toHaveTextContent("7");
    expect(figure("Referrals")).toHaveTextContent("2");
    expect(within(card).queryByText("Places held")).toBeNull();
    expect(within(card).getByText("Most in a day: 40")).toBeInTheDocument();
    const rows = within(within(card).getByRole("table", { name: "Views a day" })).getAllByRole(
      "row",
    );
    expect(rows).toHaveLength(15);
    expect(rows[14]).toHaveTextContent("40");
  });

  it("does not ask for them for anyone who does not manage it", async () => {
    const api = mockApi({
      [JOB]: () => json(job({ viewer: makeViewer() })),
      [NUMBERS]: () => apiError(403, "permission_denied", "No."),
    });
    renderApp("/opportunities/opp-1", makeSession());

    await screen.findByRole("heading", { name: "Backend Engineer" });
    expect(screen.queryByText("How it is doing")).toBeNull();
    expect(api.count(NUMBERS)).toBe(0);
  });

  it("leaves the page alone when the numbers cannot be had", async () => {
    mockApi({ [JOB]: () => json(job()), [NUMBERS]: () => apiError(500, "error", "Broken.") });
    renderApp("/opportunities/opp-1", makeSession());

    await screen.findByRole("heading", { name: "Backend Engineer" });
    expect(screen.queryByText("How it is doing")).toBeNull();
  });
});

describe("ordering the feed", () => {
  it("offers the most popular first, through the address", async () => {
    const FEED = "GET /api/v1/opportunities/";
    const api = mockApi({ [FEED]: () => json({ results: [], next: null, previous: null }) });
    const user = userEvent.setup();
    renderApp("/opportunities", makeSession());

    await user.selectOptions(await screen.findByLabelText("Order by"), "popular");

    await waitFor(() => expect(api.last(FEED)?.url.searchParams.get("sort")).toBe("popular"));
    expect(screen.getByRole("option", { name: "Most popular" })).toBeInTheDocument();
  });
});
