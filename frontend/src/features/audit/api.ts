import { useInfiniteQuery } from "@tanstack/react-query";

import { pagedQuery } from "../../services/pagination";

/** One audit record. The last four fields are only sent to the platform's admins. */
export interface AuditEntry {
  id: string;
  /** A namespaced verb: "application.status_changed". */
  action: string;
  /** Null for something the system did by itself. */
  actor: { id: string; display_name: string } | null;
  actor_type: "USER" | "SYSTEM";
  /** The kind of thing it was done to: "users.user". */
  target_type: string;
  target_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
  organization_id?: string | null;
  community_id?: string | null;
  ip?: string | null;
  request_id?: string;
}

/** What the whole trail can be narrowed by. Empty values are left out. */
export interface AuditFilters {
  actor_email: string;
  action: string;
  target_id: string;
}

export type AuditScope =
  | { kind: "platform"; filters: AuditFilters }
  | { kind: "organization"; id: string }
  | { kind: "community"; id: string };

function pathFor(scope: AuditScope): string {
  if (scope.kind === "organization") {
    return `/organizations/${scope.id}/audit-logs/`;
  }
  if (scope.kind === "community") {
    return `/communities/${scope.id}/audit-logs/`;
  }
  const given = Object.entries(scope.filters).filter(([, value]) => value);
  const search = given.length ? `?${new URLSearchParams(given).toString()}` : "";
  return `/admin/audit-logs/${search}`;
}

/** The audit trail, newest first: all of it for an admin, or one tenant's for its owners. */
export function useAuditTrail(scope: AuditScope) {
  const path = pathFor(scope);
  return useInfiniteQuery({ queryKey: ["audit", path], ...pagedQuery<AuditEntry>(path) });
}
