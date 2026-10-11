import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "../../services/http";
import { pagedQuery } from "../../services/pagination";
import { useSessionStatus } from "../auth/api";
import type {
  Invitation,
  Member,
  MyOrganization,
  Organization,
  OrganizationDetail,
  OrganizationFields,
  OrganizationRole,
  ReceivedInvitation,
} from "./types";

const keys = {
  all: ["organizations"] as const,
  list: (query: string) => ["organizations", "list", query] as const,
  mine: ["organizations", "mine"] as const,
  detail: (id: string) => ["organizations", id] as const,
  members: (id: string) => ["organizations", id, "members"] as const,
  invitations: (id: string) => ["organizations", id, "invitations"] as const,
  received: (token: string) => ["organization-invitations", token] as const,
};

export function useOrganizations(query: string) {
  const search = query ? `?${new URLSearchParams({ q: query }).toString()}` : "";
  return useInfiniteQuery({
    queryKey: keys.list(query),
    ...pagedQuery<Organization>(`/organizations/${search}`),
  });
}

export function useMyOrganizations() {
  const status = useSessionStatus();
  return useQuery({
    queryKey: keys.mine,
    queryFn: ({ signal }) => http<MyOrganization[]>("/organizations/mine/", { signal }),
    enabled: status === "authenticated",
  });
}

export function useOrganization(id: string) {
  // Keyed by session too: the `viewer` block differs for each user and for visitors.
  const status = useSessionStatus();
  return useQuery({
    queryKey: [...keys.detail(id), status],
    queryFn: ({ signal }) => http<OrganizationDetail>(`/organizations/${id}/`, { signal }),
    enabled: status !== "unknown",
  });
}

export function useCreateOrganization() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<OrganizationFields>) =>
      http<OrganizationDetail>("/organizations/", { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.all }),
  });
}

/** Mutations inside one organization refresh everything cached about it. */
function useOrganizationMutation<TInput, TResult>(
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

export function useUpdateOrganization(id: string) {
  return useOrganizationMutation(id, (body: Partial<OrganizationFields>) =>
    http<OrganizationDetail>(`/organizations/${id}/`, { method: "PATCH", body }),
  );
}

export function useMembers(id: string) {
  const status = useSessionStatus();
  return useInfiniteQuery({
    queryKey: [...keys.members(id), status],
    ...pagedQuery<Member>(`/organizations/${id}/members/`),
    enabled: status !== "unknown",
  });
}

export function useChangeRole(id: string) {
  return useOrganizationMutation(
    id,
    ({ memberId, role }: { memberId: string; role: OrganizationRole }) =>
      http<Member>(`/organizations/${id}/members/${memberId}/`, {
        method: "PATCH",
        body: { role },
      }),
  );
}

export function useSetMembershipVisibility(id: string) {
  return useOrganizationMutation(
    id,
    ({ memberId, isPublic }: { memberId: string; isPublic: boolean }) =>
      http<Member>(`/organizations/${id}/members/${memberId}/`, {
        method: "PATCH",
        body: { is_public: isPublic },
      }),
  );
}

export function useRemoveMember(id: string) {
  return useOrganizationMutation(id, (memberId: string) =>
    http<void>(`/organizations/${id}/members/${memberId}/`, { method: "DELETE" }),
  );
}

export function useLeaveOrganization(id: string) {
  return useOrganizationMutation(id, () =>
    http<void>(`/organizations/${id}/leave/`, { method: "POST" }),
  );
}

export function useTransferOwnership(id: string) {
  return useOrganizationMutation(id, (memberId: string) =>
    http<OrganizationDetail>(`/organizations/${id}/transfer-ownership/`, {
      method: "POST",
      body: { member_id: memberId },
    }),
  );
}

export function useInvitations(id: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: keys.invitations(id),
    ...pagedQuery<Invitation>(`/organizations/${id}/invitations/`),
    enabled,
  });
}

export function useInvite(id: string) {
  return useOrganizationMutation(id, (body: { email: string; role: OrganizationRole }) =>
    http<Invitation>(`/organizations/${id}/invitations/`, { method: "POST", body }),
  );
}

export function useRevokeInvitation(id: string) {
  return useOrganizationMutation(id, (invitationId: string) =>
    http<void>(`/organizations/${id}/invitations/${invitationId}/`, { method: "DELETE" }),
  );
}

export function useReceivedInvitation(token: string) {
  return useQuery({
    queryKey: keys.received(token),
    queryFn: ({ signal }) =>
      http<ReceivedInvitation>(`/organization-invitations/${token}/`, { signal }),
    retry: false,
  });
}

export function useRespondToInvitation(token: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (answer: "accept" | "decline") =>
      http<MyOrganization | undefined>(`/organization-invitations/${token}/${answer}/`, {
        method: "POST",
      }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: keys.all });
      void queryClient.invalidateQueries({ queryKey: keys.received(token) });
    },
  });
}
