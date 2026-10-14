import { useQuery } from "@tanstack/react-query";

import { http } from "../../services/http";
import type { Funnel } from "../opportunities/types";

/** How everything an organization posted is doing. */
export interface OrganizationNumbers {
  opportunities: { drafts: number; published: number; finished: number };
  funnels: Funnel[];
  /** Its open opportunities that draw the most. Up to fifteen minutes old. */
  top: {
    id: string;
    title: string;
    type: "JOB" | "EVENT";
    views: number;
    applications: number;
    registrations: number;
  }[];
}

/** How a community is doing. */
export interface CommunityNumbers {
  members: { active: number; asked_to_join: number; invited: number };
  sharing: {
    offered: number;
    waiting: number;
    declined: number;
    removed: number;
    shown: number;
    jobs_shown: number;
    events_shown: number;
    featured: number;
  };
  reports: { waiting: number; decided: number };
}

export function useOrganizationNumbers(id: string) {
  return useQuery({
    queryKey: ["insights", "organization", id],
    queryFn: ({ signal }) => http<OrganizationNumbers>(`/organizations/${id}/stats/`, { signal }),
  });
}

export function useCommunityNumbers(id: string) {
  return useQuery({
    queryKey: ["insights", "community", id],
    queryFn: ({ signal }) => http<CommunityNumbers>(`/communities/${id}/stats/`, { signal }),
  });
}
