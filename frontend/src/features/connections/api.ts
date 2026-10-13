import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "../../services/http";
import { pagedQuery } from "../../services/pagination";
import type { Connection, ConnectionState } from "./types";

export const connectionKeys = {
  all: ["connections"] as const,
  list: (state: ConnectionState) => ["connections", "list", state] as const,
  summary: ["connections", "summary"] as const,
};

export function useConnections(state: ConnectionState) {
  return useInfiniteQuery({
    queryKey: connectionKeys.list(state),
    ...pagedQuery<Connection>(`/connections/?state=${state}`),
  });
}

/** How many requests are waiting for the viewer's answer. */
export function useIncomingCount() {
  return useQuery({
    queryKey: connectionKeys.summary,
    queryFn: ({ signal }) => http<{ incoming: number }>("/connections/summary/", { signal }),
    select: (summary) => summary.incoming,
  });
}

/** After any change: the lists, the count, and the profile that shows the connect button. */
function useConnectionsChanged() {
  const queryClient = useQueryClient();
  return (userId: string) => {
    void queryClient.invalidateQueries({ queryKey: connectionKeys.all });
    void queryClient.invalidateQueries({ queryKey: ["users", userId] });
  };
}

export function useRequestConnection() {
  const changed = useConnectionsChanged();
  return useMutation({
    mutationFn: (userId: string) =>
      http<Connection>("/connections/", { method: "POST", body: { user_id: userId } }),
    onSuccess: (_, userId) => changed(userId),
    // Refused because things moved on (they asked first, or you are already connected):
    // show how it stands now.
    onError: (_, userId) => changed(userId),
  });
}

interface Target {
  connectionId: string;
  /** The other person, whose profile shows the result. */
  userId: string;
}

export function useAnswerConnection() {
  const changed = useConnectionsChanged();
  return useMutation({
    mutationFn: ({ connectionId, accept }: Target & { accept: boolean }) =>
      http<Connection | undefined>(
        `/connections/${connectionId}/${accept ? "accept" : "decline"}/`,
        { method: "POST" },
      ),
    onSettled: (_data, _error, { userId }) => changed(userId),
  });
}

/** Ends a connection, or takes back a request the viewer made. */
export function useRemoveConnection() {
  const changed = useConnectionsChanged();
  return useMutation({
    mutationFn: ({ connectionId }: Target) =>
      http<void>(`/connections/${connectionId}/`, { method: "DELETE" }),
    onSettled: (_data, _error, { userId }) => changed(userId),
  });
}
