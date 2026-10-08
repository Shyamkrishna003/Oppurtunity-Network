import { Navigate, Outlet, useLocation, useSearchParams } from "react-router";

import { Splash } from "../../components/Splash";
import { useSessionStatus } from "./api";
import { safeNext } from "./navigation";

/** Renders child routes for signed-in users; sends everyone else to sign in and back. */
export function RequireAuth() {
  const status = useSessionStatus();
  const location = useLocation();

  if (status === "unknown") {
    return <Splash />;
  }
  if (status === "anonymous") {
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }
  return <Outlet />;
}

/** For sign-in and sign-up pages: a signed-in user has no business there. */
export function AnonymousOnly() {
  const status = useSessionStatus();
  const [params] = useSearchParams();

  if (status === "unknown") {
    return <Splash />;
  }
  if (status === "authenticated") {
    return <Navigate to={safeNext(params.get("next"))} replace />;
  }
  return <Outlet />;
}
