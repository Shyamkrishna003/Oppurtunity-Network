import { Link } from "react-router";

import { useMe, useSessionStatus } from "../features/auth/api";
import { SystemStatus } from "../features/system/SystemStatus";

export function HomePage() {
  const status = useSessionStatus();
  const me = useMe();

  return (
    <>
      <h1>{me.data ? `Welcome, ${me.data.profile.display_name}` : "Opportunity Network"}</h1>
      <p className="muted">
        Jobs, events, and referrals, distributed through the communities you trust.
      </p>
      {status === "authenticated" && (
        <section className="card" aria-labelledby="next-heading">
          <h2 id="next-heading">Find your next opportunity</h2>
          <p>
            <Link to="/opportunities?sort=relevant">See the opportunities that match you best</Link>
            . They are ranked by the skills, interests and location on your profile, so{" "}
            <Link to="/settings/profile">keeping it complete</Link> puts the right ones first.
          </p>
        </section>
      )}
      {status === "anonymous" && (
        <section className="card" aria-labelledby="start-heading">
          <h2 id="start-heading">Get started</h2>
          <p>
            <Link to="/register">Create an account</Link> or <Link to="/login">sign in</Link>.
          </p>
        </section>
      )}
      <section className="card" aria-labelledby="system-status-heading">
        <h2 id="system-status-heading">System status</h2>
        <SystemStatus />
      </section>
    </>
  );
}
