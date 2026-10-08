import { vi } from "vitest";

export interface MockRequest {
  url: URL;
  headers: Record<string, string>;
  body: unknown;
}

type Handler = (request: MockRequest) => Response | Promise<Response>;

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function apiError(
  status: number,
  code: string,
  detail: string,
  errors: Record<string, string[]> = {},
): Response {
  return json({ status, code, detail, errors, request_id: "req-test" }, status);
}

export const noContent = () => new Response(null, { status: 204 });

/**
 * Replaces `fetch` with handlers keyed by "METHOD /path" (query string ignored).
 * A request without a handler fails the same way an unknown API route does.
 */
export function mockApi(routes: Record<string, Handler>) {
  const calls: (MockRequest & { key: string })[] = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    const key = `${init?.method ?? "GET"} ${url.pathname}`;
    const rawBody = init?.body;
    const request: MockRequest = {
      url,
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: typeof rawBody === "string" ? JSON.parse(rawBody) : rawBody,
    };
    calls.push({ ...request, key });
    const handler = routes[key];
    return handler ? handler(request) : apiError(404, "not_found", `No mock for ${key}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    count: (key: string) => calls.filter((call) => call.key === key).length,
    last: (key: string) => calls.filter((call) => call.key === key).at(-1),
  };
}
