import { NavLink } from "react-router";

import { Icon } from "../../components/Icon";
import { useUnreadCount } from "./api";

/** The navigation's link to the notifications page, with the number of unread ones. */
export function NotificationBell() {
  const unread = useUnreadCount();
  const count = unread.data ?? 0;
  // The exact number stops mattering long before three digits.
  const shown = count > 99 ? "99+" : String(count);
  return (
    <NavLink to="/notifications" className="tab bell">
      <Icon name="bell" />
      <span className="tab-label">Notifications</span>
      {count > 0 && (
        <>
          {" "}
          {/* Keyed by the number, so the badge pops again each time it changes. */}
          <span key={shown} className="bell-count">
            {shown} <span className="visually-hidden">unread</span>
          </span>
        </>
      )}
    </NavLink>
  );
}
