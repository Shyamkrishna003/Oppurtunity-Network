import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "../../services/http";
import { pagedQuery } from "../../services/pagination";
import { useSessionStatus } from "../auth/api";
import type { Skill } from "../auth/types";
import type {
  CloseReason,
  CommunityOpportunity,
  FeedItem,
  NewOpportunityInput,
  Opportunity,
  OpportunityDetail,
  OpportunityInput,
  OpportunityNumbers,
  OpportunityStatus,
  SavedItem,
  Share,
  ShareOption,
  Submission,
  SubmissionAction,
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

/** How the opportunity is doing. Only its managers may ask. Under the opportunity's own
 *  key, so anything that changes the opportunity also refreshes its numbers. */
export function useOpportunityNumbers(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...keys.detail(id), "numbers"],
    queryFn: ({ signal }) => http<OpportunityNumbers>(`/opportunities/${id}/stats/`, { signal }),
    enabled,
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

// --- Feed and saved ---------------------------------------------------------------------

/**
 * The feed for a set of URL parameters (passed as their query string, so two equal
 * searches share one cache entry). Keyed by session too: results, saved flags and match
 * reasons all depend on who is asking.
 */
export function useFeed(search: string) {
  const status = useSessionStatus();
  return useInfiniteQuery({
    queryKey: [...keys.all, "feed", search, status],
    ...pagedQuery<FeedItem>(`/opportunities/${search ? `?${search}` : ""}`),
    enabled: status !== "unknown",
  });
}

export function useSavedOpportunities() {
  return useInfiniteQuery({
    queryKey: [...keys.all, "saved"],
    ...pagedQuery<SavedItem>("/users/me/saved-opportunities/"),
  });
}

export function useSetSaved() {
  return useOpportunityMutation(({ id, saved }: { id: string; saved: boolean }) =>
    http<void>(`/opportunities/${id}/save/`, { method: saved ? "PUT" : "DELETE" }),
  );
}

/** Names for the skill IDs kept in the feed's URL. */
export function useSkillsById(ids: string[]) {
  const search = ids.map((id) => `id=${encodeURIComponent(id)}`).join("&");
  return useQuery({
    queryKey: ["skills", "by-id", search],
    queryFn: ({ signal }) => http<Skill[]>(`/skills/?${search}`, { signal }),
    enabled: ids.length > 0,
    staleTime: 60 * 60_000,
  });
}

// --- Sharing with communities -----------------------------------------------------------

/** The communities an opportunity was offered to. Managers only. */
export function useShares(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...keys.detail(id), "shares"],
    queryFn: ({ signal }) => http<Share[]>(`/opportunities/${id}/communities/`, { signal }),
    enabled,
  });
}

export function useShareOptions(id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...keys.detail(id), "share-options"],
    queryFn: ({ signal }) =>
      http<ShareOption[]>(`/opportunities/${id}/communities/options/`, { signal }),
    enabled,
  });
}

export function useShareWith(id: string) {
  return useOpportunityMutation((communityIds: string[]) =>
    http<Share[]>(`/opportunities/${id}/communities/`, {
      method: "POST",
      body: { community_ids: communityIds },
    }),
  );
}

export function useWithdrawShare(id: string) {
  return useOpportunityMutation((communityId: string) =>
    http<void>(`/opportunities/${id}/communities/${communityId}/`, { method: "DELETE" }),
  );
}

/** Open opportunities a community shows; `featured` limits it to the pinned ones. */
export function useCommunityOpportunities(communityId: string, featured: boolean) {
  const status = useSessionStatus();
  return useInfiniteQuery({
    queryKey: [...keys.all, "community", communityId, featured ? "featured" : "all", status],
    ...pagedQuery<CommunityOpportunity>(
      `/communities/${communityId}/opportunities/${featured ? "?featured=true" : ""}`,
    ),
    enabled: status !== "unknown",
  });
}

/** Shares waiting for the community's decision. Moderators, admins and owners only. */
export function useSubmissions(communityId: string) {
  return useInfiniteQuery({
    queryKey: [...keys.all, "community", communityId, "submissions"],
    ...pagedQuery<Submission>(`/communities/${communityId}/submissions/?status=PENDING`),
  });
}

export function useSubmissionAction(communityId: string) {
  return useOpportunityMutation(
    ({ shareId, action, reason }: { shareId: string; action: SubmissionAction; reason?: string }) =>
      http<Submission>(`/communities/${communityId}/submissions/${shareId}/${action}/`, {
        method: "POST",
        body: reason ? { reason } : undefined,
      }),
  );
}
