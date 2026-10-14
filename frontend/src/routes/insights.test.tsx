import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CommunityNumbers, OrganizationNumbers } from "../features/insights/api";
import { makeSession } from "../test/fixtures";
import { apiError, json, mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

afterEach(() => vi.unstubAllGlobals());

describe("an organization's insights", () => {
  const STATS = "GET /api/v1/organizations/o-1/stats/";
  const numbers: OrganizationNumbers = {
    opportunities: { drafts: 1, published: 3, finished: 2 },
    funnels: [
      {
        name: "applications",
        steps: [
          { key: "views", count: 200 },
          { key: "applied", count: 20 },
          { key: "hired", count: 1 },
        ],
      },
      {
        name: "registrations",
        steps: [
          { key: "views", count: 50 },
          { key: "registered", count: 10 },
          { key: "attended", count: 6 },
        ],
      },
    ],
    top: [
      {
        id: "opp-1",
        title: "Backend Engineer",
        type: "JOB",
        views: 120,
        applications: 14,
        registrations: 0,
      },
      { id: "opp-2", title: "Meetup", type: "EVENT", views: 50, applications: 0, registrations: 9 },
    ],
  };

  it("shows what was posted, how far people got, and what draws the most", async () => {
    mockApi({ [STATS]: () => json(numbers) });
    renderApp("/organizations/o-1/insights", makeSession());

    const posted = await screen.findByRole("region", { name: "What it has posted" });
    expect(within(posted).getByText("Open now").nextElementSibling).toHaveTextContent("3");
    const hired = screen.getByRole("figure", { name: "From opening it to being hired" });
    expect(within(hired).getAllByRole("listitem")[1]).toHaveTextContent(
      "Applied20, 10% of the step before",
    );
    expect(screen.getByRole("figure", { name: "From opening it to coming" })).toBeInTheDocument();
    const top = screen.getByRole("region", { name: "Drawing the most now" });
    expect(within(top).getByRole("link", { name: "Backend Engineer" })).toHaveAttribute(
      "href",
      "/opportunities/opp-1",
    );
    expect(within(top).getByText(/14 applied/)).toBeInTheDocument();
    expect(within(top).getByText(/9 places held/)).toBeInTheDocument();
  });

  it("says so when nothing was published yet", async () => {
    mockApi({
      [STATS]: () =>
        json({ opportunities: { drafts: 0, published: 0, finished: 0 }, funnels: [], top: [] }),
    });
    renderApp("/organizations/o-1/insights", makeSession());

    expect(await screen.findByText(/Nothing to show yet/)).toBeInTheDocument();
    expect(screen.queryByText("Drawing the most now")).toBeNull();
  });

  it("is refused to people who do not post for the organization", async () => {
    mockApi({ [STATS]: () => apiError(403, "permission_denied", "No.") });
    renderApp("/organizations/o-1/insights", makeSession());

    expect(
      await screen.findByText("This page is for the people who post for the organization."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the organization" })).toHaveAttribute(
      "href",
      "/organizations/o-1",
    );
  });
});

describe("a community's insights", () => {
  const STATS = "GET /api/v1/communities/c-1/stats/";
  const numbers: CommunityNumbers = {
    members: { active: 340, asked_to_join: 4, invited: 2 },
    sharing: {
      offered: 60,
      waiting: 3,
      declined: 5,
      removed: 1,
      shown: 22,
      jobs_shown: 17,
      events_shown: 5,
      featured: 2,
    },
    reports: { waiting: 1, decided: 9 },
  };

  it("shows members, what the community shows, and reports", async () => {
    mockApi({ [STATS]: () => json(numbers) });
    renderApp("/communities/c-1/insights", makeSession());

    const members = await screen.findByRole("region", { name: "Members" });
    expect(within(members).getByText("Asked to join").nextElementSibling).toHaveTextContent("4");
    const shown = screen.getByRole("region", { name: "Opportunities" });
    expect(within(shown).getByText("Shown now").nextElementSibling).toHaveTextContent("22");
    const reports = screen.getByRole("region", { name: "Reports from members" });
    expect(within(reports).getByText("Waiting").nextElementSibling).toHaveTextContent("1");
    // Says plainly what it cannot know.
    expect(screen.getByText(/nothing records which of them led someone to act/)).toBeVisible();
  });

  it("offers to try again when it fails", async () => {
    // A refusal the app does not retry by itself, unlike a server error.
    mockApi({ [STATS]: () => apiError(429, "throttled", "Slow down.") });
    renderApp("/communities/c-1/insights", makeSession());

    expect(await screen.findByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
