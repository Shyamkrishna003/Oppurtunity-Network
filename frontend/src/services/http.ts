const API_BASE = "/api/v1";

export type FieldErrors = Record<string, string[]>;

/** Error envelope returned by every API endpoint. */
interface ErrorEnvelope {
  status: number;
  code: string;
  detail: string;
  errors: FieldErrors;
  request_id: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fieldErrors: FieldErrors;
  readonly requestId: string | null;

  constructor(init: {
    status: number;
    code: string;
    detail: string;
    fieldErrors?: FieldErrors;
    requestId?: string | null;
  }) {
    super(init.detail);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.fieldErrors = init.fieldErrors ?? {};
    this.requestId = init.requestId ?? null;
  }
}

let getAccessToken: () => string | null = () => null;
let refreshAccessToken: (() => Promise<string | null>) | null = null;

export function setAccessTokenProvider(provider: () => string | null): void {
  getAccessToken = provider;
}

/**
 * Registers how to obtain a new access token when the current one is rejected.
 * The refresher resolves to the new token, or null if the session is over.
 */
export function setAccessTokenRefresher(refresher: (() => Promise<string | null>) | null): void {
  refreshAccessToken = refresher;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  /** Send without a token and never attempt a refresh (the auth endpoints themselves). */
  anonymous?: boolean;
}

function isEnvelope(value: unknown): value is ErrorEnvelope {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ErrorEnvelope).code === "string" &&
    typeof (value as ErrorEnvelope).detail === "string"
  );
}

async function toApiError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("X-Request-ID");
  const body: unknown = await response.json().catch(() => null);
  if (isEnvelope(body)) {
    return new ApiError({
      status: response.status,
      code: body.code,
      detail: body.detail,
      fieldErrors: body.errors,
      requestId: body.request_id || requestId,
    });
  }
  // Not from our API (e.g. a proxy error page).
  return new ApiError({
    status: response.status,
    code: "unexpected_response",
    detail: "The server returned an unexpected response.",
    requestId,
  });
}

async function send(path: string, options: RequestOptions, token: string | null) {
  const { method = "GET", body, signal } = options;
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const isForm = body instanceof FormData;
  if (body !== undefined && !isForm) {
    headers["Content-Type"] = "application/json";
  }

  try {
    return await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      signal,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError({
      status: 0,
      code: "network_error",
      detail: "Could not reach the server. Check your connection and try again.",
    });
  }
}

/** Calls the API. `path` is relative to the versioned base, e.g. `/opportunities/`. */
export async function http<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = options.anonymous ? null : getAccessToken();
  let response = await send(path, options, token);

  // An expired access token is replaced once, transparently, and the request repeated.
  if (response.status === 401 && token && refreshAccessToken) {
    const renewed = await refreshAccessToken();
    if (renewed) {
      response = await send(path, options, renewed);
    }
  }

  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
