import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "../../services/http";
import { pagedQuery } from "../../services/pagination";
import type { EligibleReferrers, Referral, ReferralAction, ReferralDetail } from "./types";

export type ReferralRole = "requester" | "referrer";

export const referralKeys = {
  all: ["referrals"] as const,
  list: (role: ReferralRole) => ["referrals", "list", role] as const,
  forJob: (opportunityId: string) => ["referrals", "job", opportunityId] as const,
  eligible: (opportunityId: string) => ["referrals", "eligible", opportunityId] as const,
  detail: (id: string) => ["referrals", "detail", id] as const,
};

export function useReferrals(role: ReferralRole) {
  return useInfiniteQuery({
    queryKey: referralKeys.list(role),
    ...pagedQuery<Referral>(`/referrals/requests/?role=${role}`),
  });
}

/** The viewer's own requests for one job, for that job's page. */
export function useMyReferralsForJob(opportunityId: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: referralKeys.forJob(opportunityId),
    ...pagedQuery<Referral>(`/referrals/requests/?role=requester&opportunity=${opportunityId}`),
    enabled,
  });
}

/** Whom the viewer could ask for this job. Only fetched once they open the chooser. */
export function useEligibleReferrers(opportunityId: string, enabled: boolean) {
  return useQuery({
    queryKey: referralKeys.eligible(opportunityId),
    queryFn: ({ signal }) =>
      http<EligibleReferrers>(`/jobs/${opportunityId}/eligible-referrers/`, { signal }),
    enabled,
  });
}

export function useReferral(id: string) {
  return useQuery({
    queryKey: referralKeys.detail(id),
    queryFn: ({ signal }) => http<ReferralDetail>(`/referrals/requests/${id}/`, { signal }),
  });
}

export function useRequestReferral(opportunityId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: { referrerId: string; message: string }) =>
      http<ReferralDetail>(`/jobs/${opportunityId}/referral-requests/`, {
        method: "POST",
        body: { referrer_id: request.referrerId, message: request.message },
      }),
    // Sent or refused, who can still be asked may have changed.
    onSettled: () => queryClient.invalidateQueries({ queryKey: referralKeys.all }),
  });
}

const ACTION_PATHS: Record<ReferralAction, string> = {
  accept: "accept",
  decline: "decline",
  cancel: "cancel",
  refer: "refer",
  back_out: "back-out",
};

/** Makes one of the moves the server offered the viewer for this referral. */
export function useReferralAction(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (move: { action: ReferralAction; endorsementNote?: string }) =>
      http<ReferralDetail>(`/referrals/requests/${id}/${ACTION_PATHS[move.action]}/`, {
        method: "POST",
        body: move.action === "refer" ? { endorsement_note: move.endorsementNote } : undefined,
      }),
    onSuccess: (referral) => {
      queryClient.setQueryData(referralKeys.detail(id), referral);
      void queryClient.invalidateQueries({ queryKey: ["referrals", "list"] });
      void queryClient.invalidateQueries({ queryKey: ["referrals", "job"] });
    },
    // Refused because it moved on in the meantime: show where it stands now.
    onError: () => void queryClient.invalidateQueries({ queryKey: referralKeys.all }),
  });
}
