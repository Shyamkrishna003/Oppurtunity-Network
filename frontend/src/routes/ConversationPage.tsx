import { Fragment, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useParams } from "react-router";

import { Avatar } from "../components/Avatar";
import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useMe } from "../features/auth/api";
import {
  useConversation,
  useMarkConversationRead,
  useMessages,
  useSendMessage,
  type Message,
  type Outgoing,
} from "../features/messaging/api";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

const MAX_LENGTH = 4000;
const dayFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const timeFormat = new Intl.DateTimeFormat(undefined, { timeStyle: "short" });

/** The last item that matches, or undefined. */
function lastWhere<T>(items: T[], matches: (item: T) => boolean): T | undefined {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item !== undefined && matches(item)) {
      return item;
    }
  }
  return undefined;
}

function Bubble({
  message,
  mine,
  seen,
  onRetry,
}: {
  message: Message;
  mine: boolean;
  seen: boolean;
  onRetry: () => void;
}) {
  return (
    <li className={mine ? "message message-mine" : "message"}>
      <p className="message-body">{message.body}</p>
      <div className="message-meta muted">
        <time dateTime={message.created_at}>{timeFormat.format(new Date(message.created_at))}</time>
        {message.delivery === "sending" && <span> · Sending…</span>}
        {seen && <span> · Seen</span>}
      </div>
      {message.delivery === "failed" && (
        <p className="field-error" role="alert">
          Not sent.{" "}
          <button type="button" className="link" onClick={onRetry}>
            Try again
          </button>
        </p>
      )}
    </li>
  );
}

function Composer({ onSend, disabled }: { onSend: (body: string) => void; disabled: boolean }) {
  const [text, setText] = useState("");
  const body = text.trim();

  function send() {
    if (!body || disabled) {
      return;
    }
    onSend(body);
    setText("");
  }

  return (
    <form
      className="composer"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        send();
      }}
    >
      <textarea
        aria-label="Message"
        placeholder="Write a message"
        rows={2}
        maxLength={MAX_LENGTH}
        value={text}
        disabled={disabled}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
          // Enter sends; Shift+Enter starts a new line. Not while a word is still being
          // composed with an input method, where Enter means "choose this".
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            send();
          }
        }}
      />
      <button type="submit" className="primary" disabled={disabled || !body}>
        Send
      </button>
    </form>
  );
}

export function ConversationPage() {
  const { conversationId = "" } = useParams();
  const me = useMe();
  const conversation = useConversation(conversationId);
  const thread = useMessages(conversationId);
  const send = useSendMessage(conversationId, me.data?.id ?? "");
  const markRead = useMarkConversationRead(conversationId);
  const end = useRef<HTMLDivElement>(null);

  // Pages arrive newest first; the thread reads oldest first.
  const messages = (thread.data?.pages.flatMap((page) => page.results) ?? []).slice().reverse();
  const newest = messages.at(-1);
  const newestFromThem = lastWhere(
    messages,
    (message) => message.sender_id !== me.data?.id && !message.delivery,
  );

  // Seeing a message is reading it, but only while the page is actually being looked at.
  const unreadId =
    newestFromThem && (conversation.data?.unread_count ?? 0) > 0 ? newestFromThem.id : null;
  const { mutate: sendRead } = markRead;
  useEffect(() => {
    if (!unreadId) {
      return;
    }
    const read = () => {
      if (document.visibilityState === "visible") {
        sendRead(unreadId);
      }
    };
    read();
    document.addEventListener("visibilitychange", read);
    return () => document.removeEventListener("visibilitychange", read);
  }, [unreadId, sendRead]);

  // Keep the newest message in view as the thread grows.
  const newestId = newest?.id;
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [newestId]);

  if (conversation.isPending || thread.isPending) {
    return <Splash />;
  }
  if (conversation.isError || thread.isError) {
    const failure = conversation.error ?? thread.error;
    const gone = failure instanceof ApiError && failure.status === 404;
    return (
      <>
        <h1>{gone ? "Conversation not found" : "Something went wrong"}</h1>
        <p className="muted">
          {gone
            ? "This conversation does not exist or is no longer available to you."
            : errorMessage(failure)}
        </p>
        <Link to="/messages">Back to messages</Link>
      </>
    );
  }

  const { other, other_read_at: otherReadAt } = conversation.data;
  // "Seen" goes under the last of my messages the other person has read up to.
  const lastSeen = otherReadAt
    ? lastWhere(
        messages,
        (message) =>
          message.sender_id === me.data?.id &&
          !message.delivery &&
          message.created_at <= otherReadAt,
      )
    : undefined;
  const dayOf = (message: Message) => dayFormat.format(new Date(message.created_at));
  const deliver = (outgoing: Outgoing) => send.mutate(outgoing);
  const refused =
    send.error instanceof ApiError && send.error.status !== 0 && send.error.status < 500
      ? send.error
      : null;

  return (
    <>
      <p>
        <Link to="/messages">All messages</Link>
      </p>
      <div className="page-heading">
        <h1>
          <Link to={`/users/${other.id}`} className="person">
            <Avatar name={other.display_name} url={other.avatar_url} size={40} />
            {other.display_name}
          </Link>
        </h1>
      </div>

      <section className="card thread" aria-label={`Conversation with ${other.display_name}`}>
        {thread.hasNextPage && (
          <button
            type="button"
            onClick={() => void thread.fetchNextPage()}
            disabled={thread.isFetchingNextPage}
          >
            {thread.isFetchingNextPage ? "Loading…" : "Show earlier messages"}
          </button>
        )}
        {messages.length === 0 ? (
          <p className="muted">No messages yet. Say hello.</p>
        ) : (
          <ol className="messages">
            {messages.map((message, index) => {
              const day = dayOf(message);
              const before = messages[index - 1];
              const newDay = before === undefined || dayOf(before) !== day;
              return (
                <Fragment key={message.client_id}>
                  {newDay && <li className="message-day muted">{day}</li>}
                  <Bubble
                    message={message}
                    mine={message.sender_id === me.data?.id}
                    seen={message.id === lastSeen?.id}
                    onRetry={() => deliver({ body: message.body, clientId: message.client_id })}
                  />
                </Fragment>
              );
            })}
          </ol>
        )}
        <div ref={end} />
        {refused && <Notice kind="error">{errorMessage(refused)}</Notice>}
        <Composer
          disabled={!me.data}
          onSend={(body) => deliver({ body, clientId: crypto.randomUUID() })}
        />
        <p className="field-hint">Enter sends. Shift and Enter starts a new line.</p>
      </section>
    </>
  );
}
