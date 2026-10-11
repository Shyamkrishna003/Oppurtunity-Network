import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

/** "live" only once the server has greeted us; anything else means "do not rely on pushes". */
export type StreamStatus = "offline" | "connecting" | "live";

const realtimeSlice = createSlice({
  name: "realtime",
  initialState: { status: "offline" as StreamStatus },
  reducers: {
    streamStatusChanged(state, action: PayloadAction<StreamStatus>) {
      state.status = action.payload;
    },
  },
});

export const { streamStatusChanged } = realtimeSlice.actions;
export const realtimeReducer = realtimeSlice.reducer;
