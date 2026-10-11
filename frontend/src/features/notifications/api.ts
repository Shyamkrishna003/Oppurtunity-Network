import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAppSelector } from "../../app/store";
import { http } from "../../services/http";
import { pagedQuery } from "../../services/pagination";
import { useSessionStatus } from "../auth/api";
import type { AppNotification, NotificationPreference } from "./types";

export const notificationKeys = {
  all: ["notifications"] as const,
  unreadCount: ["notifications", "unread-count"] as const,
  lists: ["notifications", "list"] as const,
  list: (unreadOnly: boolean) => ["notifications", "list", unreadOnly] as const,
  preferences: ["notifications", "preferences"] as const,
};

// The live connection normally keeps the badge current. While it is down, the badge falls
// back to a timer, and it is always refreshed when the tab is looked at again.
const UNREAD_REFRESH_MS = 60_000;

export function useUnreadCount() {
  const status = useSessionStatus();
  const live = useAppSelector((state) => state.realtime.status === "live");
  return useQuery({
    queryKey: notificationKeys.unreadCount,
    queryFn: ({ signal }) => http<{ count: number }>("/notifications/unread-count/", { signal }),
    enabled: status === "authenticated",
    refetchInterval: live ? false : UNREAD_REFRESH_MS,
    refetchOnWindowFocus: true,
    select: (data) => data.count,
  });
}

export function useNotifications(unreadOnly: boolean) {
  return useInfiniteQuery({
    queryKey: notificationKeys.list(unreadOnly),
    ...pagedQuery<AppNotification>(`/notifications/${unreadOnly ? "?unread=true" : ""}`),
  });
}

function useRefreshNotifications() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: notificationKeys.all });
}

export function useMarkRead() {
  const refresh = useRefreshNotifications();
  return useMutation({
    mutationFn: (id: string) => http<void>(`/notifications/${id}/read/`, { method: "POST" }),
    onSettled: refresh,
  });
}

export function useMarkAllRead() {
  const refresh = useRefreshNotifications();
  return useMutation({
    mutationFn: () => http<void>("/notifications/read-all/", { method: "POST" }),
    onSettled: refresh,
  });
}

interface Preferences {
  preferences: NotificationPreference[];
}

export function usePreferences() {
  return useQuery({
    queryKey: notificationKeys.preferences,
    queryFn: ({ signal }) => http<Preferences>("/users/me/notification-preferences/", { signal }),
    select: (data) => data.preferences,
  });
}

export function useSavePreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (preferences: Pick<NotificationPreference, "category" | "in_app" | "email">[]) =>
      http<Preferences>("/users/me/notification-preferences/", {
        method: "PUT",
        body: { preferences },
      }),
    onSuccess: (data) => queryClient.setQueryData(notificationKeys.preferences, data),
  });
}
