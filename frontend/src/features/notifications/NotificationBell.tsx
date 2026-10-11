import { NavLink } from "react-router";

import { useUnreadCount } from "./api";

/** Header link to the notifications page, with the number of unread ones. */
export function NotificationBell() {
  const unread = useUnreadCount();
  const count = unread.data ?? 0;
  // The exact number stops mattering long before three digits.
  const shown = count > 99 ? "99+" : String(count);
  return (
    <NavLink to="/notifications" className="bell">
      Notifications
      {count > 0 && (
        <>
          {" "}
          <span className="bell-count">
            {shown} <span className="visually-hidden">unread</span>
          </span>
        </>
      )}
    </NavLink>
  );
}
