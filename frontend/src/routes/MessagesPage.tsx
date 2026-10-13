import { Link } from "react-router";

import { Avatar } from "../components/Avatar";
import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useInbox, type Conversation } from "../features/messaging/api";
import { errorMessage } from "../services/formErrors";

const dayFormat = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const timeFormat = new Intl.DateTimeFormat(undefined, { timeStyle: "short" });

/** The time for something today, the date for anything older. */
function when(iso: string): string {
  const date = new Date(iso);
  const today = new Date().toDateString() === date.toDateString();
  return today ? timeFormat.format(date) : dayFormat.format(date);
}

function Row({ conversation }: { conversation: Conversation }) {
  const { other, unread_count: unread } = conversation;
  return (
    <li className={unread > 0 ? "entry conversation conversation-unread" : "entry conversation"}>
      <Link to={`/messages/${conversation.id}`} className="conversation-link">
        <Avatar name={other.display_name} url={other.avatar_url} size={44} />
        <span className="conversation-text">
          <strong>{other.display_name}</strong>
          <span className="muted conversation-preview">
            {conversation.last_message_preview || "No messages yet."}
          </span>
        </span>
      </Link>
      <span className="conversation-meta">
        <time className="muted" dateTime={conversation.last_message_at}>
          {when(conversation.last_message_at)}
        </time>
        {unread > 0 && (
          <span className="bell-count">
            {unread > 99 ? "99+" : unread} <span className="visually-hidden">unread</span>
          </span>
        )}
      </span>
    </li>
  );
}

export function MessagesPage() {
  const inbox = useInbox();
  const list = inbox.data?.pages.flatMap((page) => page.results) ?? [];

  if (inbox.isPending) {
    return <Splash />;
  }
  return (
    <>
      <h1>Messages</h1>
      <p className="muted">Private conversations with your connections.</p>
      <section className="card" aria-label="Your conversations">
        {inbox.isError && (
          <Notice kind="error">
            <p>{errorMessage(inbox.error)}</p>
            <button type="button" onClick={() => void inbox.refetch()}>
              Try again
            </button>
          </Notice>
        )}
        {inbox.isSuccess && list.length === 0 && (
          <p className="muted">
            No conversations yet. Open a connection&apos;s profile and choose Message to start one.{" "}
            <Link to="/connections">Your connections</Link>
          </p>
        )}
        {list.length > 0 && (
          <ul className="entry-list">
            {list.map((conversation) => (
              <Row key={conversation.id} conversation={conversation} />
            ))}
          </ul>
        )}
        {inbox.hasNextPage && (
          <button
            type="button"
            onClick={() => void inbox.fetchNextPage()}
            disabled={inbox.isFetchingNextPage}
          >
            {inbox.isFetchingNextPage ? "Loading…" : "Show more"}
          </button>
        )}
      </section>
    </>
  );
}
