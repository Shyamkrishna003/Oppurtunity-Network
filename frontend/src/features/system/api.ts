import { useQuery } from "@tanstack/react-query";

export type CheckResult = "ok" | "error";

export interface Readiness {
  status: "ok" | "unavailable";
  checks: Record<string, CheckResult>;
}

// The readiness probe lives outside the versioned API and answers 503 with the same
// body shape when a dependency is down, so it does not go through the API client.
export async function fetchReadiness(signal?: AbortSignal): Promise<Readiness> {
  const response = await fetch("/readyz", { signal, headers: { Accept: "application/json" } });
  if (response.status !== 200 && response.status !== 503) {
    throw new Error(`Readiness probe returned ${response.status}`);
  }
  return (await response.json()) as Readiness;
}

export function useReadiness() {
  return useQuery({
    queryKey: ["system", "readiness"],
    queryFn: ({ signal }) => fetchReadiness(signal),
    refetchInterval: 15_000,
    staleTime: 0,
  });
}
