import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router";

import { TextField } from "../components/Field";
import { Notice } from "../components/Notice";
import { useRequestPasswordReset } from "../features/auth/api";
import { emailSchema, type EmailValues } from "../features/auth/schemas";
import { applyApiError } from "../services/formErrors";

export function ForgotPasswordPage() {
  const request = useRequestPasswordReset();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<EmailValues>({ resolver: zodResolver(emailSchema) });

  const onSubmit = handleSubmit(async ({ email }) => {
    setFormError(null);
    try {
      await request.mutateAsync(email);
    } catch (error) {
      setFormError(applyApiError(error, setError, ["email"]));
    }
  });

  if (request.isSuccess) {
    return (
      <>
        <h1>Check your email</h1>
        <p>
          If an account uses that address, we have sent a link to reset the password. The link works
          for one hour.
        </p>
        <Link to="/login">Back to sign in</Link>
      </>
    );
  }

  return (
    <>
      <h1>Reset your password</h1>
      <p className="muted">Enter your email address and we will send you a reset link.</p>
      <form onSubmit={(event) => void onSubmit(event)} noValidate>
        {formError && <Notice kind="error">{formError}</Notice>}
        <TextField
          label="Email"
          type="email"
          autoComplete="email"
          error={errors.email?.message}
          {...register("email")}
        />
        <button type="submit" className="primary" disabled={request.isPending}>
          {request.isPending ? "Sending…" : "Send reset link"}
        </button>
      </form>
      <p className="form-links">
        <Link to="/login">Back to sign in</Link>
      </p>
    </>
  );
}
