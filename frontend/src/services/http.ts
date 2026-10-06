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

export function setAccessTokenProvider(provider: () => string | null): void {
  getAccessToken = provider;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
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

/** Calls the API. `path` is relative to the versioned base, e.g. `/opportunities/`. */
export async function http<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal } = options;
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getAccessToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const isForm = body instanceof FormData;
  if (body !== undefined && !isForm) {
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
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

  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
