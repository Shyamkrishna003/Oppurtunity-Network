import { describe, expect, it } from "vitest";

import { ApiError } from "../services/http";
import { shouldRetry } from "./queryClient";

const apiError = (status: number) => new ApiError({ status, code: "x", detail: "x" });

describe("shouldRetry", () => {
  it("never retries client errors", () => {
    expect(shouldRetry(0, apiError(404))).toBe(false);
    expect(shouldRetry(0, apiError(409))).toBe(false);
  });

  it("retries server and network errors a bounded number of times", () => {
    expect(shouldRetry(0, apiError(503))).toBe(true);
    expect(shouldRetry(1, apiError(0))).toBe(true);
    expect(shouldRetry(2, apiError(503))).toBe(false);
  });
});
