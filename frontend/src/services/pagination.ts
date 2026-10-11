import { http } from "./http";

/** One page of a cursor-paginated list. `next` is the full URL of the following page. */
export interface Page<T> {
  results: T[];
  next: string | null;
  previous: string | null;
}

const API_PREFIX = "/api/v1";

/** Turns the server's absolute `next` URL into a path the API client accepts. */
function toApiPath(url: string): string {
  const { pathname, search } = new URL(url, window.location.origin);
  return `${pathname.startsWith(API_PREFIX) ? pathname.slice(API_PREFIX.length) : pathname}${search}`;
}

/**
 * Options for `useInfiniteQuery` over a cursor-paginated endpoint: the first page comes
 * from `path`, each later one from the previous page's `next` link.
 */
export function pagedQuery<T>(path: string) {
  return {
    initialPageParam: path,
    queryFn: ({ pageParam, signal }: { pageParam: string; signal: AbortSignal }) =>
      http<Page<T>>(pageParam, { signal }),
    getNextPageParam: (last: Page<T>) => (last.next ? toApiPath(last.next) : undefined),
  };
}
