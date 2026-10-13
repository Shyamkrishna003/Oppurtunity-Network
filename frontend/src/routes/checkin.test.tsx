import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RegistrationSummary } from "../features/events/api";
import { makeSession } from "../test/fixtures";
import { apiError, json, mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const PAGE = "GET /api/v1/opportunities/ev-1/";
const SUMMARY = "GET /api/v1/events/ev-1/registrations/summary/";
const CHECK_IN = "POST /api/v1/events/ev-1/check-in/";

const summary = (overrides: Partial<RegistrationSummary> = {}): RegistrationSummary => ({
  counts: { CONFIRMED: 12, WAITLISTED: 0, CANCELLED: 1 },
  capacity: 40,
  checked_in: 3,
  checkin_open: true,
  ...overrides,
});
const ada = { id: "u-7", display_name: "Ada Lovelace", headline: "", avatar_url: null };
const routes = (overrides: Partial<RegistrationSummary> = {}) => ({
  [PAGE]: () => json({ id: "ev-1", type: "EVENT", title: "Kochi Python Meetup" }),
  [SUMMARY]: () => json(summary(overrides)),
});

afterEach(() => vi.unstubAllGlobals());

describe("checking people in", () => {
  it("checks in whoever the code belongs to and says who it was", async () => {
    let checkedIn = 3;
    const api = mockApi({
      ...routes(),
      [SUMMARY]: () => json(summary({ checked_in: checkedIn })),
      [CHECK_IN]: () => {
        checkedIn = 4;
        return json({ person: ada, checked_in_at: "2026-11-20T12:10:00Z" });
      },
    });
    renderApp("/opportunities/ev-1/check-in", makeSession());
    const user = userEvent.setup();

    expect(await screen.findByRole("heading", { name: "Check-in" })).toBeVisible();
    expect(screen.getByText(/people going are/)).toHaveTextContent(
      "3 of 12 people going are checked in.",
    );
    const box = screen.getByLabelText("Check-in code");
    expect(screen.getByRole("button", { name: "Check in" })).toBeDisabled();
    // A handheld scanner types the code and presses Enter.
    await user.type(box, "  signed-code-for-ada  {Enter}");

    expect(await screen.findByText("is checked in.")).toBeVisible();
    expect(screen.getByText("is checked in.").closest("div")).toHaveTextContent("Ada Lovelace");
    expect(api.last(CHECK_IN)?.body).toEqual({ code: "signed-code-for-ada" });
    // Ready for the next person, and the count has moved.
    expect(box).toHaveValue("");
    await waitFor(() =>
      expect(screen.getByText(/people going are/)).toHaveTextContent(
        "4 of 12 people going are checked in.",
      ),
    );
  });

  it("says when a code was already used, and nobody is checked in again", async () => {
    mockApi({
      ...routes(),
      [CHECK_IN]: () =>
        apiError(409, "already_checked_in", "This person has already been checked in.", {
          checked_in_at: ["2026-11-20T12:10:00Z"],
        }),
    });
    renderApp("/opportunities/ev-1/check-in", makeSession());

    await userEvent
      .setup()
      .type(await screen.findByLabelText("Check-in code"), "signed-code-for-ada{Enter}");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/This code was already used at \d/);
    expect(alert).toHaveTextContent("Nobody was checked in again.");
    expect(screen.queryByText("is checked in.")).toBeNull();
  });

  it("repeats the server's reason for refusing a code", async () => {
    mockApi({
      ...routes(),
      [CHECK_IN]: () => apiError(422, "invalid_code", "This code is not valid for this event."),
    });
    renderApp("/opportunities/ev-1/check-in", makeSession());

    await userEvent.setup().type(await screen.findByLabelText("Check-in code"), "made-up{Enter}");

    expect(await screen.findByText("This code is not valid for this event.")).toBeVisible();
  });

  it("says when check-in is not open", async () => {
    mockApi(routes({ checkin_open: false }));
    renderApp("/opportunities/ev-1/check-in", makeSession());

    expect(await screen.findByText(/Check-in is not open right now/)).toBeVisible();
  });

  it("offers the camera only where the browser can read codes", async () => {
    mockApi(routes());
    renderApp("/opportunities/ev-1/check-in", makeSession());
    await screen.findByLabelText("Check-in code");
    // This test browser has no barcode reader: the code box is the way in.
    expect(screen.queryByRole("button", { name: "Scan with camera" })).toBeNull();
  });

  it("is only for the people running the event", async () => {
    mockApi({
      [PAGE]: () => json({ id: "ev-1", type: "EVENT", title: "Kochi Python Meetup" }),
      [SUMMARY]: () => apiError(403, "permission_denied", "No."),
    });
    renderApp("/opportunities/ev-1/check-in", makeSession());
    expect(await screen.findByRole("heading", { name: "Check-in not available" })).toBeVisible();
    expect(screen.queryByLabelText("Check-in code")).toBeNull();
  });
});
