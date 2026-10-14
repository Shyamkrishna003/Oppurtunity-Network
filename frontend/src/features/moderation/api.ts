import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "../../services/http";
import { pagedQuery } from "../../services/pagination";
import type { Person } from "../organizations/types";

export type TargetType = "USER" | "ORGANIZATION" | "COMMUNITY" | "OPPORTUNITY";
export type ReportCategory =
  "SPAM" | "SCAM" | "HARASSMENT" | "INAPPROPRIATE" | "MISLEADING" | "OTHER";
export type ReportStatus = "OPEN" | "UNDER_REVIEW" | "ACTION_TAKEN" | "DISMISSED";
export type ActionType =
  | "HIDE"
  | "REMOVE"
  | "RESTORE"
  | "WARN"
  | "RESTRICT_POSTING"
  | "UNRESTRICT_POSTING"
  | "SUSPEND"
  | "UNSUSPEND"
  | "VERIFY"
  | "UNVERIFY";

/** Actions that last until a date, or until a moderator lifts them. */
export const TIMED_ACTIONS: readonly ActionType[] = ["SUSPEND", "RESTRICT_POSTING"];

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
  WARN: "Send a warning",
  RESTRICT_POSTING: "Stop them posting",
  UNRESTRICT_POSTING: "Let them post again",
  SUSPEND: "Suspend",
  UNSUSPEND: "Lift the suspension",
  VERIFY: "Mark as verified",
  UNVERIFY: "Withdraw verification",
};

export const ACTION_DONE_LABELS: Record<ActionType, string> = {
  HIDE: "Hidden",
  REMOVE: "Removed",
  RESTORE: "Restored",
  WARN: "Warned",
  RESTRICT_POSTING: "Stopped from posting",
  UNRESTRICT_POSTING: "Allowed to post again",
  SUSPEND: "Suspended",
  UNSUSPEND: "Suspension lifted",
  VERIFY: "Verified",
  UNVERIFY: "Verification withdrawn",
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
  /** For a suspension or restriction: when it lapses. Null means until lifted. */
  expires_at: string | null;
  actor: Person;
  created_at: string;
}

/** Anything that can be moderated, as a moderator sees it. */
export interface TargetDetail {
  target: Target;
  /** How it stands now, in words. Empty when nothing is in force. */
  standing: string[];
  /** What the viewer could do to it now. */
  possible_actions: ActionType[];
  timed_actions: ActionType[];
  actions: ModerationAction[];
}

export interface ReportDetail extends Report {
  /** Reports about the same thing that are still waiting, this one included. */
  in_progress_on_target: number;
  /** What has been done to the target, newest first. */
  actions: ModerationAction[];
  /** What can be done in answer to this report now. */
  available_actions: ActionType[];
}

/** A report sent to a community, as its moderators see it. Who made it is never included. */
export interface CommunityReport extends MyReport {
  assigned_to: Person | null;
  resolution_note: string;
}

export interface CommunityReportDetail extends CommunityReport {
  /** Reports about the same thing still waiting in this community, this one included. */
  in_progress_on_target: number;
  /** Whether the community still shows what was reported, so that it can be removed. */
  shown_in_community: boolean;
  /** Whether the viewer may decide it. Not if it is about something they manage. */
  can_decide: boolean;
}

export const moderationKeys = {
  all: ["moderation"] as const,
  mine: ["moderation", "mine"] as const,
  queue: (status: string) => ["moderation", "queue", status] as const,
  report: (id: string) => ["moderation", "report", id] as const,
  target: (type: string, id: string) => ["moderation", "target", type, id] as const,
  communityQueue: (communityId: string, status: string) =>
    ["moderation", "community", communityId, "queue", status] as const,
  communityReport: (communityId: string, id: string) =>
    ["moderation", "community", communityId, "report", id] as const,
};

export function useFileReport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (report: {
      target_type: TargetType;
      target_id: string;
      category: ReportCategory;
      description: string;
      /** Send it to this community's moderators instead of the platform's. */
      community_id?: string;
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
  | { kind: "resolve"; action: ActionType; reason: string; until: string | null };

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
      until: string | null;
    }) => http<ModerationAction>("/moderation/actions/", { method: "POST", body: act }),
    onSettled: moderated,
  });
}

export function useCommunityReports(communityId: string, status: ReportStatus | "") {
  const search = status ? `?status=${status}` : "";
  return useInfiniteQuery({
    queryKey: moderationKeys.communityQueue(communityId, status),
    ...pagedQuery<CommunityReport>(`/communities/${communityId}/reports/${search}`),
  });
}

export function useCommunityReport(communityId: string, id: string) {
  return useQuery({
    queryKey: moderationKeys.communityReport(communityId, id),
    queryFn: ({ signal }) =>
      http<CommunityReportDetail>(`/communities/${communityId}/reports/${id}/`, { signal }),
  });
}

type CommunityDecision =
  | { kind: "claim" }
  | { kind: "dismiss"; note: string }
  | { kind: "remove"; reason: string }
  // Passing it up to the platform's moderators: it leaves the community's queue.
  | { kind: "escalate" };

/** What a community's moderators can do with one of its reports. Escalating answers
 *  with nothing, since the report is then no longer theirs to see. */
export function useDecideCommunityReport(communityId: string, id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, ...body }: CommunityDecision) =>
      http<CommunityReportDetail | undefined>(
        `/communities/${communityId}/reports/${id}/${kind}/`,
        {
          method: "POST",
          body,
        },
      ),
    onSuccess: (report) => {
      if (report) {
        queryClient.setQueryData(moderationKeys.communityReport(communityId, id), report);
      }
    },
    onSettled: (_report, _error, decision) => {
      // Not the report itself once it is gone: refetching it would only find nothing.
      const gone = decision.kind === "escalate";
      void queryClient.invalidateQueries({
        queryKey: gone
          ? ["moderation", "community", communityId, "queue"]
          : ["moderation", "community", communityId],
      });
      // What the community shows may have changed.
      void queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      void queryClient.invalidateQueries({ queryKey: ["communities", communityId] });
    },
  });
}

export function useModerationTarget(type: string, id: string) {
  return useQuery({
    queryKey: moderationKeys.target(type, id),
    queryFn: ({ signal }) => http<TargetDetail>(`/moderation/targets/${type}/${id}/`, { signal }),
  });
}
