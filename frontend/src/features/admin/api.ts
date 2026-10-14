import { useQuery } from "@tanstack/react-query";

import { http } from "../../services/http";

/** Counts across the platform. "Recently" means in the last seven days. */
export interface PlatformTotals {
  /** When they were counted: the server keeps them for up to a minute. */
  generated_at: string;
  users: { total: number; verified: number; joined_recently: number; suspended: number };
  organizations: { total: number; verified: number };
  communities: { total: number };
  opportunities: {
    published: number;
    jobs: number;
    events: number;
    published_recently: number;
    hidden_or_removed: number;
  };
  outcomes: {
    applications: number;
    hires: number;
    registrations: number;
    attendances: number;
    referrals: number;
    referral_joins: number;
  };
  reports: { waiting: number; under_review: number };
}

export function usePlatformTotals() {
  return useQuery({
    queryKey: ["admin", "stats"],
    queryFn: ({ signal }) => http<PlatformTotals>("/admin/stats/", { signal }),
  });
}
