import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FeedItem, Opportunity } from "../features/opportunities/types";
import { makeMe, makeSession } from "../test/fixtures";
import { json, mockApi, noContent } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const FEED = "GET /api/v1/opportunities/";
const python = { id: "s-py", name: "Python", slug: "python" };
const react = { id: "s-re", name: "React", slug: "react" };
const page = <T,>(results: T[], next: string | null = null) =>
  json({ results, next, previous: null });

function opportunity(id: string, title: string, overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id,
    type: "JOB",
    title,
    description: "",
    status: "PUBLISHED",
    visibility: "PUBLIC",
    work_mode: "REMOTE",
    country_code: "",
    region: "",
    city: "",
    deadline: null,
    published_at: "2026-10-01T00:00:00Z",
    closed_at: null,
    close_reason: "",
    created_at: "2026-09-30T00:00:00Z",
    organization: { id: "org-1", name: "Example Labs", slug: "x", verification_status: "VERIFIED" },
    posted_by: null,
    skills: [python],
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
    ...overrides,
  };
}

const item = (id: string, title: string, extra: Partial<FeedItem> = {}): FeedItem => ({
  ...opportunity(id, title),
  is_saved: false,
  match: null,
  ...extra,
});

const withSkills = makeMe({ skills: { has: [python], interested: [] } });

afterEach(() => vi.unstubAllGlobals());

describe("feed", () => {
  it("shows a visitor the opportunities, without saving or matching", async () => {
    mockApi({ [FEED]: () => page([item("o-1", "Backend Engineer")]) });
    renderApp("/opportunities");

    expect(await screen.findByRole("link", { name: "Backend Engineer" })).toBeVisible();
    expect(screen.getByText("Example Labs")).toBeVisible();
    expect(screen.getByText("Full-time · Mid level · Remote")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Save/ })).toBeNull();
    expect(screen.queryByText(/Why it fits/)).toBeNull();
    expect(screen.queryByLabelText("Needs any of these skills")).toBeNull();
    expect(screen.getByText(/to save opportunities and see which ones match/)).toBeVisible();
    expect(screen.getByLabelText("Order by")).toHaveValue("newest");
  });

  it("searches through the address, so a search can be shared", async () => {
    const api = mockApi({
      [FEED]: ({ url }) => page(url.searchParams.get("q") ? [item("o-2", "Django Developer")] : []),
    });
    const router = renderApp("/opportunities");
    const user = userEvent.setup();

    expect(await screen.findByText("No opportunities have been published yet.")).toBeVisible();
    await user.type(screen.getByRole("searchbox"), "django");
    await user.type(screen.getByLabelText("City"), "Kochi");
    await user.type(screen.getByLabelText("Country code"), "in");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByRole("link", { name: "Django Developer" })).toBeVisible();
    expect(router.state.location.search).toBe("?q=django&city=Kochi&country=IN");
    const sent = api.last(FEED)?.url.searchParams;
    expect([sent?.get("q"), sent?.get("city"), sent?.get("country")]).toEqual([
      "django",
      "Kochi",
      "IN",
    ]);
    // A search is ordered by best match unless another order is chosen.
    expect(screen.getByLabelText("Order by")).toHaveValue("relevant");
  });

  it("applies each filter as it is chosen and can clear them all", async () => {
    const api = mockApi({ [FEED]: () => page([item("o-1", "Backend Engineer")]) });
    const router = renderApp("/opportunities");
    const user = userEvent.setup();
    await screen.findByRole("link", { name: "Backend Engineer" });
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();

    await user.selectOptions(screen.getByLabelText("Work mode"), "REMOTE");
    await user.selectOptions(screen.getByLabelText("Experience"), "SENIOR");
    await user.selectOptions(screen.getByLabelText("Posted"), "7");
    await user.selectOptions(screen.getByLabelText("Order by"), "deadline");

    await waitFor(() =>
      expect(router.state.location.search).toBe(
        "?work_mode=REMOTE&experience_level=SENIOR&posted_within=7&sort=deadline",
      ),
    );
    await waitFor(() => expect(api.last(FEED)?.url.searchParams.get("sort")).toBe("deadline"));

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(router.state.location.search).toBe(""));
    expect(screen.getByLabelText("Work mode")).toHaveValue("");
  });

  it("restores a shared search, including skills, and ignores unknown parameters", async () => {
    const api = mockApi({
      [FEED]: () => page([]),
      "GET /api/v1/skills/": ({ url }) => json(url.searchParams.has("id") ? [python, react] : []),
    });
    const router = renderApp(
      "/opportunities?skill=s-py&skill=s-re&work_mode=HYBRID&utm_source=mail&offset=40",
      makeSession(withSkills),
    );
    const user = userEvent.setup();

    expect(
      await screen.findByText("Nothing matches these filters. Try removing some."),
    ).toBeVisible();
    const sent = api.last(FEED)?.url.searchParams;
    expect(sent?.getAll("skill")).toEqual(["s-py", "s-re"]);
    expect(sent?.get("work_mode")).toBe("HYBRID");
    expect(sent?.has("utm_source") || sent?.has("offset")).toBe(false);
    expect(screen.getByLabelText("Work mode")).toHaveValue("HYBRID");

    await user.click(await screen.findByRole("button", { name: "Remove Python" }));
    await waitFor(() =>
      expect(new URLSearchParams(router.state.location.search).getAll("skill")).toEqual(["s-re"]),
    );
  });

  it("tells a signed-in user why each result fits and lets them save it", async () => {
    let saved = false;
    const api = mockApi({
      [FEED]: () =>
        page([
          item("o-1", "Backend Engineer", {
            is_saved: saved,
            match: {
              score: 13,
              reasons: [
                { kind: "skill", label: "Python" },
                { kind: "interest", label: "React" },
                { kind: "community", label: "Kochi Developers" },
                { kind: "work_mode", label: "Remote" },
              ],
            },
          }),
          item("o-2", "Sales Lead", { match: { score: 0, reasons: [] } }),
        ]),
      "PUT /api/v1/opportunities/o-1/save/": () => {
        saved = true;
        return noContent();
      },
    });
    renderApp("/opportunities", makeSession(withSkills));
    const user = userEvent.setup();

    expect(
      await screen.findByText(
        "you have Python · you are interested in React · shared in Kochi Developers · remote, as you prefer",
      ),
    ).toBeVisible();
    expect(screen.getAllByText("Why it fits:")).toHaveLength(1); // nothing claimed for no match

    const save = screen.getByRole("button", { name: "Save Backend Engineer" });
    expect(save).toHaveAttribute("aria-pressed", "false");
    await user.click(save);

    expect(await screen.findByRole("button", { name: "Saved Backend Engineer" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(api.count("PUT /api/v1/opportunities/o-1/save/")).toBe(1);
  });

  it("explains that best match needs a profile when the profile is empty", async () => {
    mockApi({ [FEED]: () => page([item("o-1", "Backend Engineer")]) });
    renderApp("/opportunities?sort=relevant", makeSession());

    expect(await screen.findByText(/yours is still empty/)).toBeVisible();
    expect(screen.getByRole("link", { name: /Add your skills/ })).toHaveAttribute(
      "href",
      "/settings/profile",
    );
  });

  it("loads further pages by following the server's next link", async () => {
    const api = mockApi({
      [FEED]: ({ url }) =>
        url.searchParams.has("cursor")
          ? page([item("o-2", "Second Page Job")])
          : page(
              [item("o-1", "First Page Job")],
              "http://localhost/api/v1/opportunities/?cursor=abc&work_mode=REMOTE",
            ),
    });
    renderApp("/opportunities?work_mode=REMOTE");
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Show more" }));

    expect(await screen.findByRole("link", { name: "Second Page Job" })).toBeVisible();
    expect(screen.getByRole("link", { name: "First Page Job" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
    // The filter travels with the cursor, because the link came from the server.
    expect(api.last(FEED)?.url.searchParams.get("work_mode")).toBe("REMOTE");
  });
});

describe("saved opportunities", () => {
  const SAVED = "GET /api/v1/users/me/saved-opportunities/";

  it("lists what was saved, marks closed ones, and removes on request", async () => {
    const api = mockApi({
      [SAVED]: () =>
        page([
          { saved_at: "2026-10-05T00:00:00Z", opportunity: opportunity("o-1", "Open Job") },
          {
            saved_at: "2026-10-03T00:00:00Z",
            opportunity: opportunity("o-2", "Finished Job", { status: "CLOSED" }),
          },
        ]),
      "DELETE /api/v1/opportunities/o-2/save/": noContent,
    });
    renderApp("/saved", makeSession());
    const user = userEvent.setup();

    const list = await screen.findByRole("region", { name: "Saved opportunities" });
    await within(list).findByRole("link", { name: "Open Job" });
    const rows = within(list)
      .getAllByRole("listitem")
      .filter((row) => row.querySelector("a"));
    expect(rows[0]).toHaveTextContent("Open Job");
    expect(rows[1]).toHaveTextContent("Finished Job");
    expect(rows[1]).toHaveTextContent("Closed");
    expect(rows[0]).not.toHaveTextContent("Closed");

    await user.click(screen.getByRole("button", { name: "Saved Finished Job" }));
    await waitFor(() => expect(api.count("DELETE /api/v1/opportunities/o-2/save/")).toBe(1));
  });

  it("points to the feed when nothing is saved, and requires signing in", async () => {
    mockApi({ [SAVED]: () => page([]) });
    renderApp("/saved", makeSession());
    expect(await screen.findByRole("link", { name: "Browse opportunities" })).toBeVisible();
  });

  it("sends visitors to sign in", async () => {
    mockApi({});
    const router = renderApp("/saved");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(router.state.location.search).toBe("?next=%2Fsaved");
  });
});

describe("saving from the job page", () => {
  const detail = (isSaved: boolean) => ({
    ...opportunity("o-1", "Backend Engineer"),
    moderation_status: "VISIBLE",
    communities: [],
    viewer: { can_manage: false, editable_fields: [], is_saved: isSaved },
  });

  it("offers Save to a signed-in reader and not to a visitor", async () => {
    const api = mockApi({
      "GET /api/v1/opportunities/o-1/": () => json(detail(true)),
      "DELETE /api/v1/opportunities/o-1/save/": noContent,
    });
    renderApp("/opportunities/o-1", makeSession());

    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Saved Backend Engineer" }));
    await waitFor(() => expect(api.count("DELETE /api/v1/opportunities/o-1/save/")).toBe(1));
  });

  it("shows no Save button to a visitor", async () => {
    mockApi({ "GET /api/v1/opportunities/o-1/": () => json(detail(false)) });
    renderApp("/opportunities/o-1");

    expect(await screen.findByRole("heading", { name: "Backend Engineer" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /Save/ })).toBeNull();
  });
});
