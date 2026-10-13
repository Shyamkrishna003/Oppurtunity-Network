import { describe, expect, it } from "vitest";

import { browserTimeZone, formatEventTime, timeZones, utcToZoned, zonedToUtc } from "./time";

describe("event times", () => {
  it("reads a wall-clock time in the event's zone, not the reader's", () => {
    expect(zonedToUtc("2026-10-20T18:00", "Asia/Kolkata")).toBe("2026-10-20T12:30:00.000Z");
    expect(zonedToUtc("2026-10-20T18:00", "UTC")).toBe("2026-10-20T18:00:00.000Z");
    expect(zonedToUtc("2026-01-15T09:00", "America/New_York")).toBe("2026-01-15T14:00:00.000Z");
    // The same clock time in summer is an hour closer to UTC there.
    expect(zonedToUtc("2026-07-15T09:00", "America/New_York")).toBe("2026-07-15T13:00:00.000Z");
  });

  it("goes back the other way, so editing shows what was typed", () => {
    for (const zone of ["Asia/Kolkata", "America/New_York", "Australia/Lord_Howe", "UTC"]) {
      for (const local of ["2026-03-08T01:30", "2026-10-20T18:00", "2026-12-31T23:45"]) {
        expect(utcToZoned(zonedToUtc(local, zone), zone)).toBe(local);
      }
    }
    expect(utcToZoned(null, "UTC")).toBe("");
  });

  it("treats empty or malformed input as no time, and an unknown zone as UTC", () => {
    expect(zonedToUtc("", "UTC")).toBeNull();
    expect(zonedToUtc("tomorrow", "UTC")).toBeNull();
    expect(zonedToUtc("2026-10-20T18:00", "Mars/Olympus")).toBe("2026-10-20T18:00:00.000Z");
  });

  it("offers the zones a browser knows, always including UTC", () => {
    const zones = timeZones();
    expect(zones).toContain("UTC");
    expect(zones).toContain("Europe/London");
    expect(zones).toContain(browserTimeZone());
    expect(new Set(zones).size).toBe(zones.length);
  });

  it("words an event's time in its own zone", () => {
    const sameDay = formatEventTime({
      start_at: "2026-10-20T12:30:00Z",
      end_at: "2026-10-20T14:30:00Z",
      timezone: "Asia/Kolkata",
    });
    expect(sameDay).toMatch(/Oct 20, 2026/);
    expect(sameDay).toMatch(/6:00\sPM – 8:00\sPM/);
    expect(sameDay.match(/2026/g)).toHaveLength(1);

    const overnight = formatEventTime({
      start_at: "2026-10-20T16:30:00Z",
      end_at: "2026-10-20T20:30:00Z",
      timezone: "Asia/Kolkata",
    });
    expect(overnight).toMatch(/Oct 20, 2026.*Oct 21, 2026/);

    expect(formatEventTime({ start_at: null, end_at: null, timezone: "UTC" })).toBe("");
  });
});
