import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockApi } from "../../test/mockApi";
import type { Skill } from "../auth/types";
import { SkillPicker } from "./SkillPicker";

const react: Skill = { id: "s1", name: "React", slug: "react" };
const reactNative: Skill = { id: "s2", name: "React Native", slug: "react-native" };

function Harness({ initial = [], canCreate = true }: { initial?: Skill[]; canCreate?: boolean }) {
  const [value, setValue] = useState(initial);
  return <SkillPicker label="Skills" value={value} onChange={setValue} canCreate={canCreate} />;
}

function renderPicker(props: Parameters<typeof Harness>[0] = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness {...props} />
    </QueryClientProvider>,
  );
}

const selected = () => screen.queryByRole("list", { name: "Skills: selected" });

afterEach(() => vi.unstubAllGlobals());

describe("SkillPicker", () => {
  it("suggests skills for the typed text and adds the chosen one", async () => {
    const api = mockApi({ "GET /api/v1/skills/": () => json([react, reactNative]) });
    renderPicker();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Skills"), "rea");
    await user.click(await screen.findByRole("button", { name: "React Native" }));

    expect(within(selected()!).getByText("React Native")).toBeVisible();
    expect(screen.getByLabelText("Skills")).toHaveValue("");
    expect(api.last("GET /api/v1/skills/")?.url.searchParams.get("q")).toBe("rea");
  });

  it("does not suggest skills that are already selected, and removes on request", async () => {
    mockApi({ "GET /api/v1/skills/": () => json([react, reactNative]) });
    renderPicker({ initial: [react] });
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Skills"), "rea");
    const suggestions = await screen.findByRole("list", { name: "Skills: suggestions" });
    expect(within(suggestions).queryByRole("button", { name: "React" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Remove React" }));
    expect(selected()).toBeNull();
  });

  it("lets a verified user add a skill that does not exist yet", async () => {
    const created: Skill = { id: "s9", name: "Apache Airflow", slug: "apache-airflow" };
    const api = mockApi({
      "GET /api/v1/skills/": () => json([]),
      "POST /api/v1/skills/": () => json(created, 201),
    });
    renderPicker();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Skills"), "Apache Airflow");
    await user.click(await screen.findByRole("button", { name: "Add “Apache Airflow”" }));

    expect(await screen.findByText("Apache Airflow")).toBeVisible();
    expect(api.last("POST /api/v1/skills/")?.body).toEqual({ name: "Apache Airflow" });
  });

  it("explains why an unverified user cannot add new skills", async () => {
    mockApi({ "GET /api/v1/skills/": () => json([]) });
    renderPicker({ canCreate: false });

    await userEvent.setup().type(screen.getByLabelText("Skills"), "Apache Airflow");

    expect(await screen.findByText(/Confirm your email address to add new skills/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /Add/ })).toBeNull();
  });
});
