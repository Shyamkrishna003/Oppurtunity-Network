import { Link, Outlet } from "react-router";

export function PublicLayout() {
  return (
    <div className="public-shell">
      <Link to="/" className="brand">
        Opportunity Network
      </Link>
      <main className="card">
        <Outlet />
      </main>
    </div>
  );
}
