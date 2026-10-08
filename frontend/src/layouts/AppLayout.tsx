import { Link, NavLink, Outlet, useNavigate } from "react-router";

import { Avatar } from "../components/Avatar";
import { useLogout, useMe, useSessionStatus } from "../features/auth/api";
import { ResendVerification } from "../features/auth/ResendVerification";

function AccountNav() {
  const status = useSessionStatus();
  const me = useMe();
  const logout = useLogout();
  const navigate = useNavigate();

  if (status === "unknown") {
    return null;
  }
  if (status === "anonymous") {
    return (
      <nav aria-label="Account" className="nav">
        <Link to="/login">Sign in</Link>
        <Link to="/register" className="button primary">
          Create account
        </Link>
      </nav>
    );
  }
  return (
    <nav aria-label="Account" className="nav">
      {me.data && (
        <NavLink to={`/users/${me.data.id}`} className="person">
          <Avatar name={me.data.profile.display_name} url={me.data.profile.avatar_url} size={28} />
          {me.data.profile.display_name}
        </NavLink>
      )}
      <NavLink to="/settings/profile">Edit profile</NavLink>
      <NavLink to="/settings/account">Account</NavLink>
      <button
        type="button"
        disabled={logout.isPending}
        onClick={() => logout.mutate(undefined, { onSettled: () => void navigate("/") })}
      >
        Sign out
      </button>
    </nav>
  );
}

function VerificationBanner() {
  const me = useMe();
  if (!me.data || me.data.email_verified) {
    return null;
  }
  return (
    <div className="banner">
      <span>
        Confirm your email address ({me.data.email}) to use every feature. We sent you a link.
      </span>
      <ResendVerification email={me.data.email} />
    </div>
  );
}

export function AppLayout() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="brand">
          Opportunity Network
        </Link>
        <AccountNav />
      </header>
      <VerificationBanner />
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
