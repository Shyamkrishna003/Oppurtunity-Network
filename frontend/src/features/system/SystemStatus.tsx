import { useReadiness } from "./api";

export function SystemStatus() {
  const { data, isPending, isError, refetch, isFetching } = useReadiness();

  if (isPending) {
    return (
      <p className="muted" role="status">
        Checking services…
      </p>
    );
  }

  if (isError) {
    return (
      <div role="alert" className="notice notice-error">
        <p>The API could not be reached.</p>
        <button type="button" onClick={() => void refetch()} disabled={isFetching}>
          Try again
        </button>
      </div>
    );
  }

  const checks = Object.entries(data.checks);
  if (checks.length === 0) {
    return <p className="muted">No service checks are configured.</p>;
  }

  return (
    <>
      <p className={data.status === "ok" ? "notice notice-ok" : "notice notice-error"}>
        {data.status === "ok" ? "All services are ready." : "Some services are unavailable."}
      </p>
      <ul className="status-list">
        {checks.map(([name, result]) => (
          <li key={name}>
            <span>{name}</span>
            <span className={result === "ok" ? "badge badge-ok" : "badge badge-error"}>
              {result}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}
