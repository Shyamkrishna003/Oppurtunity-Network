import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryClient } from "../../app/queryClient";
import { store } from "../../app/store";
import { http, setAccessTokenProvider, setAccessTokenRefresher } from "../../services/http";
import { makeMe, makeSession } from "../../test/fixtures";
import { apiError, json, mockApi } from "../../test/mockApi";
import { clearSession, establishSession, ME_QUERY_KEY, refreshSession } from "./session";

beforeEach(() => {
  clearSession();
  setAccessTokenProvider(() => store.getState().auth.accessToken);
  setAccessTokenRefresher(refreshSession);
});

afterEach(() => {
  setAccessTokenRefresher(null);
  vi.unstubAllGlobals();
});

describe("refreshSession", () => {
  it("stores the new token and the user", async () => {
    const api = mockApi({ "POST /api/v1/auth/refresh/": () => json(makeSession()) });

    await expect(refreshSession()).resolves.toBe("access-1");

    expect(store.getState().auth).toEqual({ accessToken: "access-1", status: "authenticated" });
    expect(queryClient.getQueryData(ME_QUERY_KEY)).toEqual(makeMe());
    const request = api.last("POST /api/v1/auth/refresh/");
    expect(request?.headers["X-Requested-With"]).toBe("fetch");
    expect(request?.headers.Authorization).toBeUndefined();
  });

  it("shares one request between concurrent callers", async () => {
    const api = mockApi({ "POST /api/v1/auth/refresh/": () => json(makeSession()) });

    const results = await Promise.all([refreshSession(), refreshSession(), refreshSession()]);

    expect(results).toEqual(["access-1", "access-1", "access-1"]);
    expect(api.count("POST /api/v1/auth/refresh/")).toBe(1);
  });

  it("ends the session when the server says it is over", async () => {
    establishSession(makeSession());
    mockApi({
      "POST /api/v1/auth/refresh/": () => apiError(401, "session_expired", "Sign in again."),
    });

    await expect(refreshSession()).resolves.toBeNull();

    expect(store.getState().auth).toEqual({ accessToken: null, status: "anonymous" });
    expect(queryClient.getQueryData(ME_QUERY_KEY)).toBeUndefined();
  });

  it("keeps an existing session through a server error", async () => {
    establishSession(makeSession());
    mockApi({ "POST /api/v1/auth/refresh/": () => apiError(503, "error", "Unavailable") });

    await expect(refreshSession()).resolves.toBeNull();

    expect(store.getState().auth.status).toBe("authenticated");
  });
});

describe("http with an expired access token", () => {
  it("refreshes once and repeats the request with the new token", async () => {
    establishSession(makeSession(makeMe(), "expired"));
    const api = mockApi({
      "GET /api/v1/users/me/": ({ headers }) =>
        headers.Authorization === "Bearer fresh"
          ? json(makeMe())
          : apiError(401, "authentication_failed", "Expired"),
      "POST /api/v1/auth/refresh/": () => json(makeSession(makeMe(), "fresh")),
    });

    const [first, second] = await Promise.all([http("/users/me/"), http("/users/me/")]);

    expect(first).toEqual(makeMe());
    expect(second).toEqual(makeMe());
    expect(api.count("POST /api/v1/auth/refresh/")).toBe(1);
    expect(api.count("GET /api/v1/users/me/")).toBe(4);
  });

  it("fails with the 401 and signs out when the refresh is refused", async () => {
    establishSession(makeSession());
    mockApi({
      "GET /api/v1/users/me/": () => apiError(401, "authentication_failed", "Expired"),
      "POST /api/v1/auth/refresh/": () => apiError(401, "session_expired", "Sign in again."),
    });

    await expect(http("/users/me/")).rejects.toMatchObject({ status: 401 });
    expect(store.getState().auth.status).toBe("anonymous");
  });

  it("does not try to refresh for anonymous requests", async () => {
    const api = mockApi({
      "POST /api/v1/auth/login/": () => apiError(401, "invalid_credentials", "Incorrect."),
    });

    await expect(
      http("/auth/login/", { method: "POST", body: {}, anonymous: true }),
    ).rejects.toMatchObject({ code: "invalid_credentials" });
    expect(api.count("POST /api/v1/auth/refresh/")).toBe(0);
  });
});
