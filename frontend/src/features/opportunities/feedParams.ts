/** The URL parameters the feed understands. Anything else in the address is ignored. */
export const FEED_PARAMS = [
  "q",
  "type",
  "skill",
  "city",
  "country",
  "work_mode",
  "experience_level",
  "employment_type",
  "posted_within",
  "scope",
  "sort",
] as const;

/** The part of the address that is sent to the API: known parameters only. */
export function feedSearch(params: URLSearchParams): string {
  const search = new URLSearchParams();
  for (const name of FEED_PARAMS) {
    for (const value of params.getAll(name)) {
      if (value) {
        search.append(name, value);
      }
    }
  }
  return search.toString();
}
