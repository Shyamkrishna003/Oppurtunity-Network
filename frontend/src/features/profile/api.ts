import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "../../services/http";
import { ME_QUERY_KEY } from "../auth/session";
import type { Me, OwnProfile, Skill, SkillSets } from "../auth/types";
import type { BlockedUser, Education, Experience, Page, PublicProfile } from "./types";

function useSetMe() {
  const queryClient = useQueryClient();
  return (update: (me: Me) => Me) =>
    queryClient.setQueryData<Me>(ME_QUERY_KEY, (me) => (me ? update(me) : me));
}

export function useUpdateProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: Partial<OwnProfile>) =>
      http<Me>("/users/me/", { method: "PATCH", body: changes }),
    onSuccess: (me) => {
      queryClient.setQueryData<Me>(ME_QUERY_KEY, me);
      void queryClient.invalidateQueries({ queryKey: ["users", me.id] });
    },
  });
}

export function useUploadAvatar() {
  const setMe = useSetMe();
  return useMutation({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return http<OwnProfile>("/users/me/avatar/", { method: "PUT", body });
    },
    onSuccess: (profile) => setMe((me) => ({ ...me, profile })),
  });
}

export function useRemoveAvatar() {
  const setMe = useSetMe();
  return useMutation({
    mutationFn: () => http<OwnProfile>("/users/me/avatar/", { method: "DELETE" }),
    onSuccess: (profile) => setMe((me) => ({ ...me, profile })),
  });
}

export function useSkillSuggestions(query: string) {
  return useQuery({
    queryKey: ["skills", "suggest", query],
    queryFn: ({ signal }) =>
      http<Skill[]>(`/skills/?${new URLSearchParams({ q: query }).toString()}`, { signal }),
    enabled: query.length > 0,
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
}

export function useCreateSkill() {
  return useMutation({
    mutationFn: (name: string) => http<Skill>("/skills/", { method: "POST", body: { name } }),
  });
}

export function useSaveSkills() {
  const setMe = useSetMe();
  return useMutation({
    mutationFn: (sets: SkillSets) =>
      http<SkillSets>("/users/me/skills/", {
        method: "PUT",
        body: {
          has: sets.has.map((skill) => skill.id),
          interested: sets.interested.map((skill) => skill.id),
        },
      }),
    onSuccess: (skills) => setMe((me) => ({ ...me, skills })),
  });
}

export type HistoryKind = "experiences" | "educations";
type HistoryEntry<K extends HistoryKind> = K extends "experiences" ? Experience : Education;

const historyKey = (kind: HistoryKind) => ["me", kind] as const;

export function useHistory<K extends HistoryKind>(kind: K) {
  return useQuery({
    queryKey: historyKey(kind),
    queryFn: ({ signal }) => http<HistoryEntry<K>[]>(`/users/me/${kind}/`, { signal }),
  });
}

export function useSaveHistoryEntry<K extends HistoryKind>(kind: K) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: Omit<HistoryEntry<K>, "id"> & { id?: string }) =>
      id
        ? http<HistoryEntry<K>>(`/users/me/${kind}/${id}/`, { method: "PATCH", body })
        : http<HistoryEntry<K>>(`/users/me/${kind}/`, { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: historyKey(kind) }),
  });
}

export function useDeleteHistoryEntry(kind: HistoryKind) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => http<void>(`/users/me/${kind}/${id}/`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: historyKey(kind) }),
  });
}

export function useProfile(userId: string) {
  return useQuery({
    queryKey: ["users", userId],
    queryFn: ({ signal }) => http<PublicProfile>(`/users/${userId}/`, { signal }),
  });
}

const BLOCKS_KEY = ["me", "blocks"] as const;

export function useBlockedUsers() {
  return useQuery({
    queryKey: BLOCKS_KEY,
    queryFn: ({ signal }) => http<Page<BlockedUser>>("/users/me/blocks/", { signal }),
  });
}

export function useSetBlocked() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, blocked }: { userId: string; blocked: boolean }) =>
      http<void>(`/users/${userId}/block/`, { method: blocked ? "PUT" : "DELETE" }),
    onSuccess: (_, { userId }) => {
      void queryClient.invalidateQueries({ queryKey: BLOCKS_KEY });
      void queryClient.invalidateQueries({ queryKey: ["users", userId] });
    },
  });
}
