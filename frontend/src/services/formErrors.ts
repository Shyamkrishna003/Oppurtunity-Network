import type { FieldValues, Path, UseFormSetError } from "react-hook-form";

import { ApiError } from "./http";

/**
 * Puts the server's per-field messages on the matching form fields and returns the
 * message to show for the form as a whole (null when every error found a field).
 */
export function applyApiError<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  fields: readonly Path<T>[],
): string | null {
  if (!(error instanceof ApiError)) {
    return "Something went wrong. Try again.";
  }
  let matched = false;
  for (const field of fields) {
    const messages = error.fieldErrors[field];
    if (messages?.length) {
      setError(field, { type: "server", message: messages.join(" ") });
      matched = true;
    }
  }
  return matched ? null : error.message;
}

export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong. Try again.";
}
