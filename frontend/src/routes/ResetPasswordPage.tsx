import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router";

import { TextField } from "../components/Field";
import { Notice } from "../components/Notice";
import { useConfirmPasswordReset } from "../features/auth/api";
import { resetSchema, type ResetValues } from "../features/auth/schemas";
import { clearSession } from "../features/auth/session";
import { applyApiError } from "../services/formErrors";

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const uid = params.get("uid") ?? "";
  const token = params.get("token") ?? "";
  const confirm = useConfirmPasswordReset();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<ResetValues>({ resolver: zodResolver(resetSchema) });

  const onSubmit = handleSubmit(async ({ new_password }) => {
    setFormError(null);
    try {
      await confirm.mutateAsync({ uid, token, new_password });
      // The reset ended every session on the server, including one in this browser.
      clearSession();
      await navigate("/login?reset=done", { replace: true });
    } catch (error) {
      setFormError(applyApiError(error, setError, ["new_password"]));
    }
  });

  if (!uid || !token) {
    return (
      <>
        <h1>Choose a new password</h1>
        <Notice kind="error">This link is incomplete. Open the link from your email again.</Notice>
        <Link to="/forgot-password">Request a new link</Link>
      </>
    );
  }

  return (
    <>
      <h1>Choose a new password</h1>
      <form onSubmit={(event) => void onSubmit(event)} noValidate>
        {formError && (
          <Notice kind="error">
            {formError} <Link to="/forgot-password">Request a new link</Link>
          </Notice>
        )}
        <TextField
          label="New password"
          type="password"
          autoComplete="new-password"
          hint="At least 10 characters."
          error={errors.new_password?.message}
          {...register("new_password")}
        />
        <TextField
          label="Repeat new password"
          type="password"
          autoComplete="new-password"
          error={errors.confirm?.message}
          {...register("confirm")}
        />
        <button type="submit" className="primary" disabled={confirm.isPending}>
          {confirm.isPending ? "Saving…" : "Change password"}
        </button>
      </form>
    </>
  );
}
