import { QueryClientProvider } from "@tanstack/react-query";
import { Provider as StoreProvider } from "react-redux";
import { RouterProvider } from "react-router";

import { setAccessTokenProvider } from "../services/http";
import { queryClient } from "./queryClient";
import { router } from "./router";
import { store } from "./store";

// The HTTP client reads the token through this hook so it never imports the store.
setAccessTokenProvider(() => store.getState().auth.accessToken);

export function App() {
  return (
    <StoreProvider store={store}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StoreProvider>
  );
}
