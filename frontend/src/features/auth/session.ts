import { queryClient } from "../../app/queryClient";
import { store } from "../../app/store";
import { ApiError, http } from "../../services/http";
import { sessionCleared, sessionEstablished } from "./authSlice";
import type { Me, Session } from "./types";

export const ME_QUERY_KEY = ["me"] as const;

// The refresh cookie is only accepted together with this header (CSRF defence).
const COOKIE_REQUEST = { anonymous: true, headers: { "X-Requested-With": "fetch" } } as const;

export function establishSession(session: Session): void {
  queryClient.setQueryData<Me>(ME_QUERY_KEY, session.user);
  store.dispatch(sessionEstablished(session.access_token));
}

export function clearSession(): void {
  store.dispatch(sessionCleared());
  // Everything cached belongs to the user who just left.
  queryClient.clear();
}

let refreshInFlight: Promise<string | null> | null = null;

/**
 * Exchanges the refresh cookie for a new access token. Concurrent callers share one
 * request: the cookie is single-use, so parallel refreshes would invalidate each other.
 * Resolves to the token, or null when there is no session.
 */
export function refreshSession(): Promise<string | null> {
  refreshInFlight ??= http<Session>("/auth/refresh/", { method: "POST", ...COOKIE_REQUEST })
    .then((session) => {
      establishSession(session);
      return session.access_token;
    })
    .catch((error: unknown) => {
      // Only a definite "no" ends the session; a network blip or server error does not.
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        clearSession();
      } else if (store.getState().auth.status === "unknown") {
        store.dispatch(sessionCleared());
      }
      return null;
    })
    .finally(() => {
      refreshInFlight = null;
    });
  return refreshInFlight;
}

export async function endSession(): Promise<void> {
  try {
    await http<void>("/auth/logout/", { method: "POST", ...COOKIE_REQUEST });
  } finally {
    // Signed out locally even if the server could not be reached.
    clearSession();
  }
}
