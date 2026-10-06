import { isRouteErrorResponse, useRouteError } from "react-router";

import { ApiError } from "../services/http";

/** Route-level error boundary: catches render and loader failures for the whole tree. */
export function RouteError() {
  const error = useRouteError();

  let title = "Something went wrong";
  let reference: string | null = null;
  if (isRouteErrorResponse(error) && error.status === 404) {
    title = "Page not found";
  } else if (error instanceof ApiError) {
    reference = error.requestId;
  }

  return (
    <div className="public-shell" role="alert">
      <main className="card">
        <h1>{title}</h1>
        <p className="muted">Reload the page to try again.</p>
        {reference && <p className="muted">Reference: {reference}</p>}
        <button type="button" onClick={() => window.location.reload()}>
          Reload
        </button>
      </main>
    </div>
  );
}
