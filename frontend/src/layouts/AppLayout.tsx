import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";

import { Avatar } from "../components/Avatar";
import { Icon, type IconName } from "../components/Icon";
import { useLogout, useMe, useSessionStatus } from "../features/auth/api";
import { ResendVerification } from "../features/auth/ResendVerification";
import type { Me } from "../features/auth/types";
import { NotificationBell } from "../features/notifications/NotificationBell";

function Tab({
  to,
  icon,
  label,
  end,
  home,
}: {
  to: string;
  icon: IconName;
  label: string;
  end?: boolean;
  home?: boolean;
}) {
  return (
    <NavLink to={to} end={end} className={home ? "tab tab-home" : "tab"}>
      <Icon name={icon} />
      <span className="tab-label">{label}</span>
    </NavLink>
  );
}

/** Everything about the signed-in person that is not a destination people visit all day. */
function AccountMenu({ me }: { me: Me }) {
  const location = useLocation();
  // Remembered as "open on this page", so going anywhere closes the menu by itself.
  const [openAt, setOpenAt] = useState<string | null>(null);
  const open = openAt === location.key;
  const setOpen = (value: boolean) => setOpenAt(value ? location.key : null);
  const container = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const logout = useLogout();

  useEffect(() => {
    if (!open) {
      return;
    }
    const onPointerDown = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) {
        setOpenAt(null);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpenAt(null);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const { display_name: name, avatar_url: avatarUrl } = me.profile;
  return (
    <div ref={container} className={open ? "menu open" : "menu"}>
      <button
        type="button"
        className="menu-button"
        aria-expanded={open}
        aria-controls="account-menu"
        onClick={() => setOpen(!open)}
      >
        <Avatar name={name} url={avatarUrl} size={34} />
        Menu
        <Icon name="chevron" size={18} />
      </button>
      {/* Shown and hidden by the stylesheet, so the links are always in the page. */}
      <nav id="account-menu" aria-label="Account" className="menu-panel">
        <NavLink to={`/users/${me.id}`}>
          <Avatar name={name} url={avatarUrl} size={28} />
          {name}
        </NavLink>
        <div className="menu-divider" />
        <NavLink to="/my/opportunities">
          <Icon name="megaphone" />
          My opportunities
        </NavLink>
        <NavLink to="/saved">
          <Icon name="bookmark" />
          Saved
        </NavLink>
        <NavLink to="/settings/profile">
          <Icon name="pencil" />
          Edit profile
        </NavLink>
        <NavLink to="/settings/account">
          <Icon name="gear" />
          Account
        </NavLink>
        <div className="menu-divider" />
        <button
          type="button"
          disabled={logout.isPending}
          onClick={() => {
            // Signing out removes this menu from the page, and a mutation's own callbacks
            // do not run for a component that is gone; the promise's do.
            void logout
              .mutateAsync()
              .catch(() => undefined)
              .finally(() => void navigate("/"));
          }}
        >
          <Icon name="logout" />
          Sign out
        </button>
      </nav>
    </div>
  );
}

function AccountArea() {
  const status = useSessionStatus();
  const me = useMe();

  if (status === "anonymous") {
    return (
      <nav aria-label="Account" className="rail-foot">
        <Link to="/login">Sign in</Link>
        <Link to="/register" className="button primary">
          Create account
        </Link>
      </nav>
    );
  }
  if (status === "authenticated" && me.data) {
    return (
      <div className="rail-foot">
        <AccountMenu me={me.data} />
      </div>
    );
  }
  return null;
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
  const signedIn = useSessionStatus() === "authenticated";
  return (
    <div className="app-shell">
      {/* The left rail on a wide screen. On a phone: a top bar, with the navigation moved
          to a tab bar at the bottom by the stylesheet. */}
      <header className={signedIn ? "rail" : "rail rail-guest"}>
        <Link to="/" className="brand">
          <span className="brand-mark">
            <Icon name="spark" size={20} />
          </span>
          <span className="brand-name">Opportunity Network</span>
        </Link>
        <nav aria-label="Main" className="rail-nav">
          <Tab to="/" icon="home" label="Home" end home />
          <Tab to="/opportunities" icon="compass" label="Opportunities" end />
          <Tab to="/communities" icon="people" label="Communities" />
          <Tab to="/organizations" icon="building" label="Organizations" />
          {signedIn && (
            <>
              <Tab to="/applications" icon="briefcase" label="My applications" />
              <NotificationBell />
            </>
          )}
        </nav>
        <AccountArea />
      </header>
      <div className="app-body">
        <VerificationBanner />
        <main className="app-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
