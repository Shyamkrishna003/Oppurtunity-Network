import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { store } from "../app/store";
import { safeNext } from "../features/auth/navigation";
import { makeMe, makeSession } from "../test/fixtures";
import { apiError, json, mockApi, noContent } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const readiness = { "GET /readyz": () => json({ status: "ok", checks: { database: "ok" } }) };

afterEach(() => vi.unstubAllGlobals());

async function signIn(email = "ada@example.com", password = "correct-horse-battery") {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Email"), email);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("sign in", () => {
  it("signs in and continues to the page the visitor wanted", async () => {
    const api = mockApi({
      ...readiness,
      "POST /api/v1/auth/login/": () => json(makeSession()),
    });
    const router = renderApp("/login?next=%2F%3Ffrom%3Dlogin");

    await signIn();

    expect(await screen.findByRole("heading", { name: "Welcome, Ada Lovelace" })).toBeVisible();
    expect(router.state.location.search).toBe("?from=login");
    expect(api.last("POST /api/v1/auth/login/")?.body).toEqual({
      email: "ada@example.com",
      password: "correct-horse-battery",
    });
    expect(store.getState().auth.accessToken).toBe("access-1");
  });

  it("shows the server's message when the credentials are wrong", async () => {
    mockApi({
      "POST /api/v1/auth/login/": () =>
        apiError(401, "invalid_credentials", "Incorrect email or password."),
    });
    renderApp("/login");

    await signIn();

    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("validates before calling the server", async () => {
    const api = mockApi({});
    renderApp("/login");

    await userEvent.setup().click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Enter your email address.")).toBeVisible();
    expect(screen.getByText("Enter your password.")).toBeVisible();
    expect(api.calls).toHaveLength(0);
  });

  it("sends signed-in users away from the sign-in page", async () => {
    mockApi(readiness);
    renderApp("/login", makeSession());

    expect(await screen.findByRole("heading", { name: "Welcome, Ada Lovelace" })).toBeVisible();
  });

  it.each(["//evil.example", "https://evil.example", "/\\evil.example", null])(
    "ignores an unsafe return address: %s",
    (next) => {
      expect(safeNext(next)).toBe("/");
    },
  );
});

describe("protected pages", () => {
  it("send anonymous visitors to sign in and remember where they were going", async () => {
    mockApi({});
    const router = renderApp("/settings/account");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(router.state.location.search).toBe("?next=%2Fsettings%2Faccount");
  });
});

describe("register", () => {
  async function fill() {
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Name"), "Ada Lovelace");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: "Create account" }));
  }

  it("tells the visitor to check their email", async () => {
    mockApi({ "POST /api/v1/auth/register/": () => json({ detail: "Sent." }, 202) });
    renderApp("/register");

    await fill();

    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeVisible();
    expect(screen.getByText("ada@example.com")).toBeVisible();
    expect(store.getState().auth.status).toBe("anonymous");
  });

  it("shows server-side password errors on the field", async () => {
    mockApi({
      "POST /api/v1/auth/register/": () =>
        apiError(422, "weak_password", "Choose a stronger password.", {
          password: ["This password is too common."],
        }),
    });
    renderApp("/register");

    await fill();

    expect(await screen.findByText("This password is too common.")).toBeVisible();
    expect(screen.getByLabelText("Password")).toHaveAttribute("aria-invalid", "true");
  });
});

describe("verify email", () => {
  it("confirms the address from the link", async () => {
    const api = mockApi({ "POST /api/v1/auth/verify-email/": noContent });
    renderApp("/verify-email?token=abc");

    expect(await screen.findByRole("heading", { name: "Email confirmed" })).toBeVisible();
    expect(api.last("POST /api/v1/auth/verify-email/")?.body).toEqual({ token: "abc" });
    expect(api.count("POST /api/v1/auth/verify-email/")).toBe(1);
  });

  it("offers a new link when the link has expired", async () => {
    const api = mockApi({
      "POST /api/v1/auth/verify-email/": () =>
        apiError(400, "token_expired", "This link has expired. Request a new one."),
      "POST /api/v1/auth/verify-email/resend/": () => json({ detail: "Sent." }, 202),
    });
    renderApp("/verify-email?token=old", makeSession(makeMe({ email_verified: false })));

    expect(await screen.findByText("This link has expired. Request a new one.")).toBeVisible();
    await userEvent.setup().click(screen.getByRole("button", { name: "Send a new link" }));

    await waitFor(() =>
      expect(api.last("POST /api/v1/auth/verify-email/resend/")?.body).toEqual({
        email: "ada@example.com",
      }),
    );
  });

  it("explains an incomplete link without calling the server", () => {
    const api = mockApi({});
    renderApp("/verify-email");

    expect(screen.getByRole("alert")).toHaveTextContent("This link is incomplete.");
    expect(api.calls).toHaveLength(0);
  });
});

describe("reset password", () => {
  it("sets the new password and returns to sign in", async () => {
    const api = mockApi({ "POST /api/v1/auth/password-reset/confirm/": noContent });
    renderApp("/reset-password?uid=u1&token=t1", makeSession());
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("New password"), "a-brand-new-passphrase");
    await user.type(screen.getByLabelText("Repeat new password"), "a-brand-new-passphrase");
    await user.click(screen.getByRole("button", { name: "Change password" }));

    expect(await screen.findByText(/Your password has been changed/)).toBeVisible();
    expect(api.last("POST /api/v1/auth/password-reset/confirm/")?.body).toEqual({
      uid: "u1",
      token: "t1",
      new_password: "a-brand-new-passphrase",
    });
    expect(store.getState().auth.status).toBe("anonymous");
  });

  it("requires the two passwords to match", async () => {
    const api = mockApi({});
    renderApp("/reset-password?uid=u1&token=t1");
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("New password"), "a-brand-new-passphrase");
    await user.type(screen.getByLabelText("Repeat new password"), "something-else-entirely");
    await user.click(screen.getByRole("button", { name: "Change password" }));

    expect(await screen.findByText("The passwords do not match.")).toBeVisible();
    expect(api.calls).toHaveLength(0);
  });
});
