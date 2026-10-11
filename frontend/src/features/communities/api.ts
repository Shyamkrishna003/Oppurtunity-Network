import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "../../services/http";
import { pagedQuery } from "../../services/pagination";
import { useSessionStatus } from "../auth/api";
import type {
  Community,
  CommunityDetail,
  CommunityFields,
  CommunityMember,
  CommunityRole,
  ListableStatus,
  MemberAction,
  MyCommunity,
  Rule,
} from "./types";

const keys = {
  all: ["communities"] as const,
  list: (query: string) => ["communities", "list", query] as const,
  mine: ["communities", "mine"] as const,
  detail: (id: string) => ["communities", id] as const,
  members: (id: string, status: ListableStatus) => ["communities", id, "members", status] as const,
};

export function useCommunities(query: string) {
  // Keyed by session: signed-in users also see private communities they belong to.
  const status = useSessionStatus();
  const search = query ? `?${new URLSearchParams({ q: query }).toString()}` : "";
  return useInfiniteQuery({
    queryKey: [...keys.list(query), status],
    ...pagedQuery<Community>(`/communities/${search}`),
    enabled: status !== "unknown",
  });
}

export function useMyCommunities() {
  const status = useSessionStatus();
  return useQuery({
    queryKey: keys.mine,
    queryFn: ({ signal }) => http<MyCommunity[]>("/communities/mine/", { signal }),
    enabled: status === "authenticated",
  });
}

export function useCommunity(id: string) {
  // Keyed by session too: the `viewer` block differs for each user and for visitors.
  const status = useSessionStatus();
  return useQuery({
    queryKey: [...keys.detail(id), status],
    queryFn: ({ signal }) => http<CommunityDetail>(`/communities/${id}/`, { signal }),
    enabled: status !== "unknown",
  });
}

export function useCreateCommunity() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<CommunityFields>) =>
      http<CommunityDetail>("/communities/", { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.all }),
  });
}

/** Mutations inside one community refresh everything cached about communities. */
function useCommunityMutation<TInput, TResult>(
  id: string,
  mutationFn: (input: TInput) => Promise<TResult>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.all }),
    // A refused change usually means the page is out of date (a role changed elsewhere).
    onError: () => queryClient.invalidateQueries({ queryKey: keys.detail(id) }),
  });
}

export function useUpdateCommunity(id: string) {
  return useCommunityMutation(id, (body: Partial<CommunityFields>) =>
    http<CommunityDetail>(`/communities/${id}/`, { method: "PATCH", body }),
  );
}

export function useReplaceRules(id: string) {
  return useCommunityMutation(id, (rules: Rule[]) =>
    http<CommunityDetail>(`/communities/${id}/rules/`, { method: "PUT", body: { rules } }),
  );
}

export function useJoinCommunity(id: string) {
  return useCommunityMutation(id, () =>
    http<CommunityDetail>(`/communities/${id}/join/`, { method: "POST" }),
  );
}

export function useLeaveCommunity(id: string) {
  return useCommunityMutation(id, () =>
    http<void>(`/communities/${id}/leave/`, { method: "POST" }),
  );
}

export function useCommunityMembers(id: string, status: ListableStatus, enabled = true) {
  return useInfiniteQuery({
    queryKey: keys.members(id, status),
    ...pagedQuery<CommunityMember>(`/communities/${id}/members/?status=${status}`),
    enabled,
  });
}

export function useMemberAction(id: string) {
  return useCommunityMutation(
    id,
    ({ memberId, action }: { memberId: string; action: MemberAction }) =>
      http<CommunityMember>(`/communities/${id}/members/${memberId}/${action}/`, {
        method: "POST",
      }),
  );
}

export function useChangeCommunityRole(id: string) {
  return useCommunityMutation(id, ({ memberId, role }: { memberId: string; role: CommunityRole }) =>
    http<CommunityMember>(`/communities/${id}/members/${memberId}/`, {
      method: "PATCH",
      body: { role },
    }),
  );
}

/** Not bound to one community: the profile page picks the community when inviting. */
export function useInviteToCommunity() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ communityId, userId }: { communityId: string; userId: string }) =>
      http<CommunityMember>(`/communities/${communityId}/invitations/`, {
        method: "POST",
        body: { user_id: userId },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.all }),
  });
}
