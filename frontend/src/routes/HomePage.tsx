import { SystemStatus } from "../features/system/SystemStatus";

export function HomePage() {
  return (
    <>
      <h1>Opportunity Network</h1>
      <p className="muted">
        Jobs, events, and referrals, distributed through the communities you trust.
      </p>
      <section className="card" aria-labelledby="system-status-heading">
        <h2 id="system-status-heading">System status</h2>
        <SystemStatus />
      </section>
    </>
  );
}
