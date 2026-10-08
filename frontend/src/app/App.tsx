import { QueryClientProvider } from "@tanstack/react-query";
import { Provider as StoreProvider } from "react-redux";
import { RouterProvider } from "react-router";

import { refreshSession } from "../features/auth/session";
import { setAccessTokenProvider, setAccessTokenRefresher } from "../services/http";
import { queryClient } from "./queryClient";
import { router } from "./router";
import { store } from "./store";

// The HTTP client reads the token through these hooks so it never imports the store.
setAccessTokenProvider(() => store.getState().auth.accessToken);
setAccessTokenRefresher(refreshSession);

// The access token lives in memory only, so every page load starts by asking the server
// whether the refresh cookie still holds a session.
void refreshSession();

export function App() {
  return (
    <StoreProvider store={store}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StoreProvider>
  );
}
