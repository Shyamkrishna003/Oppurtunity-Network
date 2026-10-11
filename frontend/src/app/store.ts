import { configureStore } from "@reduxjs/toolkit";
import { useDispatch, useSelector } from "react-redux";

import { authReducer } from "../features/auth/authSlice";
import { realtimeReducer } from "../features/realtime/realtimeSlice";

// Global client state only. Server data belongs in TanStack Query, never here.
export const store = configureStore({
  reducer: {
    auth: authReducer,
    realtime: realtimeReducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

export const useAppDispatch = useDispatch.withTypes<AppDispatch>();
export const useAppSelector = useSelector.withTypes<RootState>();
