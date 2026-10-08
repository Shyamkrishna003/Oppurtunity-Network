import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { Provider as StoreProvider } from "react-redux";
import { createMemoryRouter, RouterProvider } from "react-router";

import { queryClient } from "../app/queryClient";
import { routes } from "../app/router";
import { store } from "../app/store";
import { sessionCleared } from "../features/auth/authSlice";
import { clearSession, establishSession } from "../features/auth/session";
import type { Session } from "../features/auth/types";

/**
 * Renders the real route tree at `path`. Pass a session to start signed in; otherwise
 * the visitor is anonymous (the startup refresh is assumed to have found no session).
 */
export function renderApp(path: string, session?: Session) {
  clearSession();
  if (session) {
    establishSession(session);
  } else {
    store.dispatch(sessionCleared());
  }
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <StoreProvider store={store}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StoreProvider>,
  );
  return router;
}
