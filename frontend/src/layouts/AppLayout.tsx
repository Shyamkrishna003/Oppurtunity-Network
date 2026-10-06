import { Link, Outlet } from "react-router";

export function AppLayout() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="brand">
          Opportunity Network
        </Link>
        <nav aria-label="Account">
          <Link to="/login">Sign in</Link>
        </nav>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
