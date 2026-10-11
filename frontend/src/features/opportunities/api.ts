import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "../../services/http";
import { pagedQuery } from "../../services/pagination";
import { useSessionStatus } from "../auth/api";
import type {
  CloseReason,
  NewOpportunityInput,
  Opportunity,
  OpportunityDetail,
  OpportunityInput,
  OpportunityStatus,
} from "./types";

const keys = {
  all: ["opportunities"] as const,
  detail: (id: string) => ["opportunities", id] as const,
  mine: (status: string) => ["opportunities", "mine", status] as const,
};

export function useOpportunity(id: string) {
  // Keyed by session: what is visible, and the `viewer` block, depend on who is asking.
  const status = useSessionStatus();
  return useQuery({
    queryKey: [...keys.detail(id), status],
    queryFn: ({ signal }) => http<OpportunityDetail>(`/opportunities/${id}/`, { signal }),
    enabled: status !== "unknown",
  });
}

export function useMyOpportunities(status: OpportunityStatus | "") {
  const search = status ? `?status=${status}` : "";
  return useInfiniteQuery({
    queryKey: keys.mine(status),
    ...pagedQuery<Opportunity>(`/users/me/opportunities/${search}`),
  });
}

/** Every write refreshes whatever is cached about opportunities. */
function useOpportunityMutation<TInput, TResult>(mutationFn: (input: TInput) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.all }),
  });
}

export function useCreateOpportunity() {
  return useOpportunityMutation((body: NewOpportunityInput) =>
    http<OpportunityDetail>("/opportunities/", { method: "POST", body }),
  );
}

export function useUpdateOpportunity(id: string) {
  return useOpportunityMutation((body: Partial<OpportunityInput>) =>
    http<OpportunityDetail>(`/opportunities/${id}/`, { method: "PATCH", body }),
  );
}

export function usePublishOpportunity(id: string) {
  return useOpportunityMutation(() =>
    http<OpportunityDetail>(`/opportunities/${id}/publish/`, { method: "POST" }),
  );
}

export function useCloseOpportunity(id: string) {
  return useOpportunityMutation((reason: CloseReason) =>
    http<OpportunityDetail>(`/opportunities/${id}/close/`, { method: "POST", body: { reason } }),
  );
}

export function useArchiveOpportunity(id: string) {
  return useOpportunityMutation(() =>
    http<OpportunityDetail>(`/opportunities/${id}/archive/`, { method: "POST" }),
  );
}

export function useDeleteOpportunity(id: string) {
  return useOpportunityMutation(() => http<void>(`/opportunities/${id}/`, { method: "DELETE" }));
}
