import { Link, useSearchParams } from "react-router";

import { Avatar } from "../components/Avatar";
import { Notice } from "../components/Notice";
import {
  useMarkAllRead,
  useMarkRead,
  useNotifications,
  useUnreadCount,
} from "../features/notifications/api";
import type { AppNotification } from "../features/notifications/types";
import { errorMessage } from "../services/formErrors";

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function Row({ notification }: { notification: AppNotification }) {
  const markRead = useMarkRead();
  return (
    <li className={notification.is_read ? "notification" : "notification notification-unread"}>
      {notification.actor ? (
        <Avatar
          name={notification.actor.display_name}
          url={notification.actor.avatar_url}
          size={36}
        />
      ) : (
        <span className="avatar avatar-initial avatar-system" aria-hidden="true">
          i
        </span>
      )}
      <div>
        {/* Opening it is reading it. The link is still a real link if the request fails. */}
        <Link
          to={notification.url}
          onClick={() => {
            if (!notification.is_read) {
              markRead.mutate(notification.id);
            }
          }}
        >
          <strong>{notification.title}</strong>
        </Link>
        {!notification.is_read && <span className="badge badge-ok"> New</span>}
        <div>{notification.body}</div>
        <div className="muted">{timeFormat.format(new Date(notification.created_at))}</div>
      </div>
      {!notification.is_read && (
        <button
          type="button"
          disabled={markRead.isPending}
          onClick={() => markRead.mutate(notification.id)}
        >
          Mark as read <span className="visually-hidden">: {notification.title}</span>
        </button>
      )}
    </li>
  );
}

export function NotificationsPage() {
  const [params, setParams] = useSearchParams();
  const unreadOnly = params.get("unread") === "true";
  const notifications = useNotifications(unreadOnly);
  const unread = useUnreadCount();
  const markAll = useMarkAllRead();
  const list = notifications.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <>
      <div className="page-heading">
        <h1>Notifications</h1>
        <Link to="/settings/notifications" className="button">
          Notification settings
        </Link>
      </div>

      <section className="card" aria-label="Your notifications">
        <div className="page-heading">
          <div className="field field-checkbox">
            <input
              id="unread-only"
              type="checkbox"
              checked={unreadOnly}
              onChange={(event) => setParams(event.target.checked ? { unread: "true" } : {})}
            />
            <label htmlFor="unread-only">Unread only</label>
          </div>
          {(unread.data ?? 0) > 0 && (
            <button type="button" disabled={markAll.isPending} onClick={() => markAll.mutate()}>
              Mark all as read
            </button>
          )}
        </div>
        {markAll.isError && <Notice kind="error">{errorMessage(markAll.error)}</Notice>}

        {notifications.isPending && (
          <p className="muted" role="status">
            Loading…
          </p>
        )}
        {notifications.isError && (
          <Notice kind="error">
            <p>{errorMessage(notifications.error)}</p>
            <button type="button" onClick={() => void notifications.refetch()}>
              Try again
            </button>
          </Notice>
        )}
        {notifications.isSuccess && list.length === 0 && (
          <p className="muted">
            {unreadOnly
              ? "You have read everything."
              : "Nothing yet. Notifications will appear here."}
          </p>
        )}
        {list.length > 0 && (
          <ul className="entry-list">
            {list.map((notification) => (
              <Row key={notification.id} notification={notification} />
            ))}
          </ul>
        )}
        {notifications.hasNextPage && (
          <button
            type="button"
            onClick={() => void notifications.fetchNextPage()}
            disabled={notifications.isFetchingNextPage}
          >
            {notifications.isFetchingNextPage ? "Loading…" : "Show more"}
          </button>
        )}
      </section>
    </>
  );
}
