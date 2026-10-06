import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SystemStatus } from "./SystemStatus";

function renderWithFetch(response: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(response));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SystemStatus />
    </QueryClientProvider>,
  );
}

const readiness = (status: number, body: unknown) => () =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

afterEach(() => vi.unstubAllGlobals());

describe("SystemStatus", () => {
  it("shows a loading state first", () => {
    renderWithFetch(() => new Promise(() => {}));

    expect(screen.getByRole("status")).toHaveTextContent("Checking services");
  });

  it("lists each check when everything is ready", async () => {
    renderWithFetch(readiness(200, { status: "ok", checks: { database: "ok", cache: "ok" } }));

    expect(await screen.findByText("All services are ready.")).toBeInTheDocument();
    expect(screen.getByText("database")).toBeInTheDocument();
    expect(screen.getByText("cache")).toBeInTheDocument();
  });

  it("shows which dependency is down on a 503", async () => {
    renderWithFetch(
      readiness(503, { status: "unavailable", checks: { database: "ok", cache: "error" } }),
    );

    expect(await screen.findByText("Some services are unavailable.")).toBeInTheDocument();
    expect(screen.getByText("error")).toBeInTheDocument();
  });

  it("offers a retry when the API is unreachable", async () => {
    renderWithFetch(() => Promise.resolve(new Response("Bad Gateway", { status: 502 })));

    expect(await screen.findByRole("alert")).toHaveTextContent("The API could not be reached.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });
});
