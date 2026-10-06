import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, http, setAccessTokenProvider } from "./http";

function mockFetch(response: Response) {
  const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(response.clone()));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function mockFetchFailure(error: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(() => Promise.reject(error)),
  );
}

function json(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessTokenProvider(() => null);
});

describe("http", () => {
  it("returns parsed JSON and prefixes the versioned base path", async () => {
    const fetchMock = mockFetch(json({ id: "1" }));

    await expect(http<{ id: string }>("/opportunities/")).resolves.toEqual({ id: "1" });
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/opportunities/");
  });

  it("sends the bearer token only when a session exists", async () => {
    const fetchMock = mockFetch(json({}));
    await http("/users/me/");
    expect(fetchMock.mock.calls[0]?.[1]?.headers).not.toHaveProperty("Authorization");

    setAccessTokenProvider(() => "token-123");
    await http("/users/me/");
    expect(fetchMock.mock.calls[1]?.[1]?.headers).toMatchObject({
      Authorization: "Bearer token-123",
    });
  });

  it("serializes JSON bodies", async () => {
    const fetchMock = mockFetch(json({}));

    await http("/reports/", { method: "POST", body: { category: "SPAM" } });

    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.body).toBe('{"category":"SPAM"}');
    expect(init?.headers).toMatchObject({ "Content-Type": "application/json" });
  });

  it("returns undefined for 204 responses", async () => {
    mockFetch(new Response(null, { status: 204 }));

    await expect(http("/opportunities/1/save/", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("maps the error envelope onto ApiError", async () => {
    mockFetch(
      json(
        {
          status: 400,
          code: "validation_error",
          detail: "The request data is invalid.",
          errors: { title: ["This field is required."] },
          request_id: "req-1",
        },
        { status: 400 },
      ),
    );

    const error = await http("/opportunities/", { method: "POST", body: {} }).catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 400,
      code: "validation_error",
      message: "The request data is invalid.",
      fieldErrors: { title: ["This field is required."] },
      requestId: "req-1",
    });
  });

  it("handles non-API error responses such as proxy pages", async () => {
    mockFetch(
      new Response("<html>Bad Gateway</html>", {
        status: 502,
        headers: { "X-Request-ID": "req-2" },
      }),
    );

    await expect(http("/opportunities/")).rejects.toMatchObject({
      status: 502,
      code: "unexpected_response",
      requestId: "req-2",
    });
  });

  it("reports network failures as ApiError with status 0", async () => {
    mockFetchFailure(new TypeError("Failed to fetch"));

    await expect(http("/opportunities/")).rejects.toMatchObject({
      status: 0,
      code: "network_error",
    });
  });

  it("lets aborts propagate unchanged so queries can cancel", async () => {
    mockFetchFailure(new DOMException("Aborted", "AbortError"));

    await expect(http("/opportunities/")).rejects.toMatchObject({ name: "AbortError" });
  });
});
