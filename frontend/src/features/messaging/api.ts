import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";

import { useAppSelector } from "../../app/store";
import { http } from "../../services/http";
import { pagedQuery, type Page } from "../../services/pagination";
import { useSessionStatus } from "../auth/api";
import type { Person } from "../organizations/types";

export interface Conversation {
  id: string;
  other: Person;
  last_message_at: string;
  last_message_preview: string;
  unread_count: number;
  /** How far the other person has read; null if they have not opened it. */
  other_read_at: string | null;
  created_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  body: string;
  /** Chosen by the sender's device; the same one again is a retry, never a second message. */
  client_id: string;
  created_at: string;
  /** Only on a message this device is still sending, or failed to send. */
  delivery?: "sending" | "failed";
}

export const messagingKeys = {
  all: ["conversations"] as const,
  inbox: ["conversations", "inbox"] as const,
  unread: ["conversations", "unread"] as const,
  detail: (id: string) => ["conversations", id, "detail"] as const,
  messages: (id: string) => ["conversations", id, "messages"] as const,
};

// The live connection normally keeps the badge current; without it, a timer does.
const UNREAD_REFRESH_MS = 60_000;

export function useUnreadConversations() {
  const status = useSessionStatus();
  const live = useAppSelector((state) => state.realtime.status === "live");
  return useQuery({
    queryKey: messagingKeys.unread,
    queryFn: ({ signal }) => http<{ count: number }>("/conversations/unread-count/", { signal }),
    enabled: status === "authenticated",
    refetchInterval: live ? false : UNREAD_REFRESH_MS,
    refetchOnWindowFocus: true,
    select: (data) => data.count,
  });
}

export function useInbox() {
  return useInfiniteQuery({
    queryKey: messagingKeys.inbox,
    ...pagedQuery<Conversation>("/conversations/"),
  });
}

export function useConversation(id: string) {
  return useQuery({
    queryKey: messagingKeys.detail(id),
    queryFn: ({ signal }) => http<Conversation>(`/conversations/${id}/`, { signal }),
  });
}

/** A conversation's messages, newest page first; each page is newest first too. */
export function useMessages(id: string) {
  return useInfiniteQuery({
    queryKey: messagingKeys.messages(id),
    ...pagedQuery<Message>(`/conversations/${id}/messages/`),
  });
}

/** Opens the conversation with someone, creating it if there is none. */
export function useStartConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      http<Conversation>("/conversations/", { method: "POST", body: { user_id: userId } }),
    onSuccess: (conversation) => {
      queryClient.setQueryData(messagingKeys.detail(conversation.id), conversation);
      void queryClient.invalidateQueries({ queryKey: messagingKeys.inbox });
    },
  });
}

type Thread = InfiniteData<Page<Message>, string>;

/** Puts a message at the newest end of a cached thread, replacing the one with the same
 *  `client_id` if it is there (the copy shown while sending, or an earlier attempt). */
function place(thread: Thread | undefined, message: Message): Thread | undefined {
  const first = thread?.pages[0];
  if (!thread || !first) {
    return thread;
  }
  const without = thread.pages.map((page) => ({
    ...page,
    results: page.results.filter((item) => item.client_id !== message.client_id),
  }));
  return {
    ...thread,
    pages: [{ ...first, results: [message, ...(without[0]?.results ?? [])] }, ...without.slice(1)],
  };
}

export interface Outgoing {
  body: string;
  /** Kept across retries, so a message that did arrive is never sent a second time. */
  clientId: string;
}

/**
 * Sends a message. It appears in the thread at once, marked as sending; the server's copy
 * replaces it, or it is marked as failed and can be sent again with the same `clientId`.
 */
export function useSendMessage(conversationId: string, senderId: string) {
  const queryClient = useQueryClient();
  const key = messagingKeys.messages(conversationId);
  const show = (message: Message) =>
    queryClient.setQueryData<Thread>(key, (thread) => place(thread, message));

  return useMutation({
    mutationFn: ({ body, clientId }: Outgoing) =>
      http<Message>(`/conversations/${conversationId}/messages/`, {
        method: "POST",
        body: { body, client_id: clientId },
      }),
    onMutate: async ({ body, clientId }) => {
      // A refetch already under way would put the thread back as it was before this message.
      await queryClient.cancelQueries({ queryKey: key });
      const pending: Message = {
        id: `pending-${clientId}`,
        conversation_id: conversationId,
        sender_id: senderId,
        body,
        client_id: clientId,
        created_at: new Date().toISOString(),
        delivery: "sending",
      };
      show(pending);
      return pending;
    },
    onSuccess: (message) => {
      show(message);
      void queryClient.invalidateQueries({ queryKey: messagingKeys.inbox });
    },
    onError: (_error, _outgoing, pending) => {
      if (pending) {
        show({ ...pending, delivery: "failed" });
      }
    },
  });
}

/** Tells the server how far the viewer has read. Safe to call often: it only moves forward. */
export function useMarkConversationRead(conversationId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (upToMessageId: string) =>
      http<void>(`/conversations/${conversationId}/read/`, {
        method: "POST",
        body: { up_to_message_id: upToMessageId },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: messagingKeys.unread });
      void queryClient.invalidateQueries({ queryKey: messagingKeys.inbox });
    },
  });
}
