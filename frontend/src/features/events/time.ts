/**
 * Event times. They are stored in UTC together with the time zone the event happens in,
 * and are typed and shown as wall-clock time in that zone, wherever the reader is.
 */

/** The reader's own zone, as a starting point for a new event. */
export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function timeZones(): string[] {
  const known =
    typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
  // Not every browser lists UTC, and a browser's own zone must always be choosable.
  return [...new Set(["UTC", browserTimeZone(), ...known])].sort();
}

function safeZone(timeZone: string): string {
  try {
    new Intl.DateTimeFormat(undefined, { timeZone });
    return timeZone;
  } catch {
    return "UTC";
  }
}

/** The wall-clock reading of an instant in a zone, as the numbers of a UTC timestamp. */
function wallClock(instant: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(new Date(instant));
  const get = (type: string) => Number(parts.find((part) => part.type === type)?.value);
  return Date.UTC(
    get("year"),
    get("month") - 1,
    get("day"),
    get("hour"),
    get("minute"),
    get("second"),
  );
}

/** "2026-10-20T18:00" as read on a clock in `timeZone`, to the instant it names (ISO, UTC).
 *  Empty or unreadable input gives null. */
export function zonedToUtc(local: string, timeZone: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(local);
  if (!match) {
    return null;
  }
  const [year, month, day, hour, minute] = match.slice(1).map(Number) as [
    number,
    number,
    number,
    number,
    number,
  ];
  const zone = safeZone(timeZone);
  const wanted = Date.UTC(year, month - 1, day, hour, minute);
  // Start from "as if it were UTC" and correct by how far the zone is off at that moment;
  // a second pass settles the hours around a daylight-saving change.
  let instant = wanted;
  for (let pass = 0; pass < 2; pass += 1) {
    instant = wanted - (wallClock(instant, zone) - instant);
  }
  return new Date(instant).toISOString();
}

/** An instant as "2026-10-20T18:00" on a clock in `timeZone`, for a date-and-time input. */
export function utcToZoned(iso: string | null, timeZone: string): string {
  if (!iso) {
    return "";
  }
  return new Date(wallClock(new Date(iso).getTime(), safeZone(timeZone)))
    .toISOString()
    .slice(0, 16);
}

/** "Tue, Oct 20, 2026, 6:00 PM – 8:00 PM GMT+5:30", in the event's own zone. */
export function formatEventTime(event: {
  start_at: string | null;
  end_at: string | null;
  timezone: string;
}): string {
  if (!event.start_at) {
    return "";
  }
  const timeZone = safeZone(event.timezone || browserTimeZone());
  const day = new Intl.DateTimeFormat(undefined, {
    timeZone,
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  const time = new Intl.DateTimeFormat(undefined, { timeZone, hour: "numeric", minute: "2-digit" });
  const zoneName =
    new Intl.DateTimeFormat(undefined, { timeZone, timeZoneName: "short" })
      .formatToParts(new Date(event.start_at))
      .find((part) => part.type === "timeZoneName")?.value ?? "";

  const start = new Date(event.start_at);
  let text = `${day.format(start)}, ${time.format(start)}`;
  if (event.end_at) {
    const end = new Date(event.end_at);
    const sameDay = day.format(start) === day.format(end);
    text += ` – ${sameDay ? "" : `${day.format(end)}, `}${time.format(end)}`;
  }
  return `${text} ${zoneName}`.trim();
}
