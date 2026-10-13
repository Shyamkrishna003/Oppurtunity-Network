import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "../../services/http";
import { pagedQuery } from "../../services/pagination";
import type { Person } from "../organizations/types";

export type TargetType = "USER" | "ORGANIZATION" | "COMMUNITY" | "OPPORTUNITY";
export type ReportCategory =
  "SPAM" | "SCAM" | "HARASSMENT" | "INAPPROPRIATE" | "MISLEADING" | "OTHER";
export type ReportStatus = "OPEN" | "UNDER_REVIEW" | "ACTION_TAKEN" | "DISMISSED";
export type ActionType = "HIDE" | "REMOVE" | "RESTORE";

export const CATEGORY_LABELS: Record<ReportCategory, string> = {
  SPAM: "Spam",
  SCAM: "Scam or fraud",
  HARASSMENT: "Harassment or hate",
  INAPPROPRIATE: "Inappropriate content",
  MISLEADING: "False or misleading",
  OTHER: "Something else",
};

export const REPORT_STATUS_LABELS: Record<ReportStatus, string> = {
  OPEN: "Waiting",
  UNDER_REVIEW: "Under review",
  ACTION_TAKEN: "Action taken",
  DISMISSED: "No action needed",
};

export const TARGET_LABELS: Record<TargetType, string> = {
  USER: "Person",
  ORGANIZATION: "Organization",
  COMMUNITY: "Community",
  OPPORTUNITY: "Opportunity",
};

/** What a moderator can do, worded as the button that does it. */
export const ACTION_LABELS: Record<ActionType, string> = {
  HIDE: "Hide it",
  REMOVE: "Remove it for good",
  RESTORE: "Restore it",
};

export const ACTION_DONE_LABELS: Record<ActionType, string> = {
  HIDE: "Hidden",
  REMOVE: "Removed",
  RESTORE: "Restored",
};

export interface Target {
  type: TargetType;
  id: string;
  name: string;
  /** A path in this app. */
  url: string;
}

/** A report as the person who made it sees it. */
export interface MyReport {
  id: string;
  target: Target;
  category: ReportCategory;
  description: string;
  status: ReportStatus;
  created_at: string;
  resolved_at: string | null;
}

/** A report as the moderators see it. */
export interface Report extends MyReport {
  reporter: Person;
  assigned_to: Person | null;
  resolution_note: string;
}

export interface ModerationAction {
  id: string;
  action_type: ActionType;
  reason: string;
  actor: Person;
  created_at: string;
}

export interface ReportDetail extends Report {
  /** Reports about the same thing that are still waiting, this one included. */
  in_progress_on_target: number;
  /** What has been done to the target, newest first. */
  actions: ModerationAction[];
  /** What can be done in answer to this report now. */
  available_actions: ActionType[];
}

export const moderationKeys = {
  all: ["moderation"] as const,
  mine: ["moderation", "mine"] as const,
  queue: (status: string) => ["moderation", "queue", status] as const,
  report: (id: string) => ["moderation", "report", id] as const,
};

export function useFileReport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (report: {
      target_type: TargetType;
      target_id: string;
      category: ReportCategory;
      description: string;
    }) => http<MyReport>("/reports/", { method: "POST", body: report }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: moderationKeys.mine }),
  });
}

export function useMyReports() {
  return useInfiniteQuery({
    queryKey: moderationKeys.mine,
    ...pagedQuery<MyReport>("/reports/mine/"),
  });
}

export function useReportQueue(status: ReportStatus | "") {
  const search = status ? `?status=${status}` : "";
  return useInfiniteQuery({
    queryKey: moderationKeys.queue(status),
    ...pagedQuery<Report>(`/moderation/reports/${search}`),
  });
}

export function useReport(id: string) {
  return useQuery({
    queryKey: moderationKeys.report(id),
    queryFn: ({ signal }) => http<ReportDetail>(`/moderation/reports/${id}/`, { signal }),
  });
}

/** After a moderator does anything: the report's page, the queues, and whatever was acted
 *  on, which may now be hidden or back. */
function useModerated() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: moderationKeys.all });
    void queryClient.invalidateQueries({ queryKey: ["opportunities"] });
  };
}

type Decision =
  | { kind: "claim" }
  | { kind: "dismiss"; note: string }
  | { kind: "resolve"; action: ActionType; reason: string };

/** Claim, dismiss or act on a report. */
export function useDecideReport(id: string) {
  const moderated = useModerated();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, ...body }: Decision) =>
      http<ReportDetail>(`/moderation/reports/${id}/${kind}/`, { method: "POST", body }),
    onSuccess: (report) => queryClient.setQueryData(moderationKeys.report(id), report),
    // Also after a refusal: it usually means a colleague decided first.
    onSettled: moderated,
  });
}

/** Act on something without a report, such as restoring what was hidden. */
export function useModerate() {
  const moderated = useModerated();
  return useMutation({
    mutationFn: (act: {
      target_type: TargetType;
      target_id: string;
      action: ActionType;
      reason: string;
    }) => http<ModerationAction>("/moderation/actions/", { method: "POST", body: act }),
    onSettled: moderated,
  });
}
