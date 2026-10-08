import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAppSelector } from "../../app/store";
import { http } from "../../services/http";
import { endSession, establishSession, ME_QUERY_KEY } from "./session";
import type { Me, Session } from "./types";

const anonymous = { anonymous: true } as const;

export function useSessionStatus() {
  return useAppSelector((state) => state.auth.status);
}

/** The signed-in user. Only enabled once a session exists. */
export function useMe() {
  const status = useSessionStatus();
  return useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: ({ signal }) => http<Me>("/users/me/", { signal }),
    enabled: status === "authenticated",
    staleTime: 5 * 60_000,
  });
}

export function useLogin() {
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      http<Session>("/auth/login/", { method: "POST", body, ...anonymous }),
    onSuccess: establishSession,
  });
}

export function useRegister() {
  return useMutation({
    mutationFn: (body: { email: string; password: string; display_name: string }) =>
      http<{ detail: string }>("/auth/register/", { method: "POST", body, ...anonymous }),
  });
}

export function useLogout() {
  return useMutation({ mutationFn: endSession });
}

/** Confirms the address as a query so a re-render or StrictMode cannot submit twice. */
export function useVerifyEmail(token: string) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: ["auth", "verify-email", token],
    queryFn: async () => {
      await http<void>("/auth/verify-email/", { method: "POST", body: { token }, ...anonymous });
      await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
      return true;
    },
    enabled: token !== "",
    retry: false,
    staleTime: Infinity,
    gcTime: Infinity,
  });
}

export function useResendVerification() {
  return useMutation({
    mutationFn: (email: string) =>
      http<{ detail: string }>("/auth/verify-email/resend/", {
        method: "POST",
        body: { email },
        ...anonymous,
      }),
  });
}

export function useRequestPasswordReset() {
  return useMutation({
    mutationFn: (email: string) =>
      http<{ detail: string }>("/auth/password-reset/", {
        method: "POST",
        body: { email },
        ...anonymous,
      }),
  });
}

export function useConfirmPasswordReset() {
  return useMutation({
    mutationFn: (body: { uid: string; token: string; new_password: string }) =>
      http<void>("/auth/password-reset/confirm/", { method: "POST", body, ...anonymous }),
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      http<Session>("/auth/password-change/", { method: "POST", body }),
    onSuccess: establishSession,
  });
}
