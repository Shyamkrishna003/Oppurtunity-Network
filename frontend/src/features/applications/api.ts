import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "../../services/http";
import { pagedQuery } from "../../services/pagination";
import type { Application, ApplicationDetail, ApplicationStatus } from "./types";

export const applicationKeys = {
  all: ["applications"] as const,
  mine: (status: string) => ["applications", "mine", status] as const,
  detail: (id: string) => ["applications", "detail", id] as const,
};

export function useMyApplications(status: ApplicationStatus | "") {
  const search = status ? `?status=${status}` : "";
  return useInfiniteQuery({
    queryKey: applicationKeys.mine(status),
    ...pagedQuery<Application>(`/applications/${search}`),
  });
}

export function useApplication(id: string) {
  return useQuery({
    queryKey: applicationKeys.detail(id),
    queryFn: ({ signal }) => http<ApplicationDetail>(`/applications/${id}/`, { signal }),
  });
}

/** After anything changes an application: its own page, the lists, and the job page that
 *  shows "you applied". */
function useApplicationChanged() {
  const queryClient = useQueryClient();
  return (application: ApplicationDetail) => {
    queryClient.setQueryData(applicationKeys.detail(application.id), application);
    void queryClient.invalidateQueries({ queryKey: ["applications", "mine"] });
    void queryClient.invalidateQueries({
      queryKey: ["opportunities", application.opportunity.id],
    });
  };
}

export function useApply(opportunityId: string) {
  const changed = useApplicationChanged();
  return useMutation({
    mutationFn: ({ resume, coverNote }: { resume: File; coverNote: string }) => {
      const body = new FormData();
      body.append("resume", resume);
      body.append("cover_note", coverNote);
      return http<ApplicationDetail>(`/jobs/${opportunityId}/apply/`, { method: "POST", body });
    },
    onSuccess: changed,
  });
}

export function useWithdraw(id: string) {
  const changed = useApplicationChanged();
  return useMutation({
    mutationFn: () => http<ApplicationDetail>(`/applications/${id}/withdraw/`, { method: "POST" }),
    onSuccess: changed,
  });
}

/**
 * Asks for a download link and follows it. The link only works for a minute, so it is
 * requested at the moment of the click and never kept.
 */
export function useDownloadResume(id: string) {
  return useMutation({
    mutationFn: async () => {
      const { url } = await http<{ url: string }>(`/applications/${id}/resume/`);
      // Served as an attachment, so following it starts a download without leaving the page.
      const link = document.createElement("a");
      link.href = url;
      link.rel = "noopener";
      document.body.append(link);
      link.click();
      link.remove();
    },
  });
}
