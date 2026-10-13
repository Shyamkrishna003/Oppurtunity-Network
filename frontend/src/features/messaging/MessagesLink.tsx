import { NavLink } from "react-router";

import { Icon } from "../../components/Icon";
import { useUnreadConversations } from "./api";

/** The navigation's link to messages, with the number of conversations waiting. */
export function MessagesLink() {
  const unread = useUnreadConversations();
  const count = unread.data ?? 0;
  const shown = count > 99 ? "99+" : String(count);
  return (
    <NavLink to="/messages" className="tab bell">
      <Icon name="chat" />
      <span className="tab-label">Messages</span>
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
