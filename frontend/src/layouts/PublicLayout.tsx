import { Link, Outlet } from "react-router";

import { Icon } from "../components/Icon";

export function PublicLayout() {
  return (
    <div className="public-shell">
      <Link to="/" className="brand">
        <span className="brand-mark">
          <Icon name="spark" size={20} />
        </span>
        Opportunity Network
      </Link>
      <p className="public-tagline">Jobs, events and referrals from communities you trust.</p>
      <main className="card">
        <Outlet />
      </main>
    </div>
  );
}
