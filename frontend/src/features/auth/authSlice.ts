import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

export type SessionStatus = "unknown" | "authenticated" | "anonymous";

interface AuthState {
  // Kept in memory only: never written to localStorage or sessionStorage.
  accessToken: string | null;
  status: SessionStatus;
}

const initialState: AuthState = {
  accessToken: null,
  status: "unknown",
};

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    sessionEstablished(state, action: PayloadAction<string>) {
      state.accessToken = action.payload;
      state.status = "authenticated";
    },
    sessionCleared(state) {
      state.accessToken = null;
      state.status = "anonymous";
    },
  },
});

export const { sessionEstablished, sessionCleared } = authSlice.actions;
export const authReducer = authSlice.reducer;
