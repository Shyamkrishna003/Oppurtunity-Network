import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useSearchParams } from "react-router";

import { TextField } from "../components/Field";
import { Notice } from "../components/Notice";
import { useLogin } from "../features/auth/api";
import { loginSchema, type LoginValues } from "../features/auth/schemas";
import { applyApiError } from "../services/formErrors";

export function LoginPage() {
  const [params] = useSearchParams();
  const login = useLogin();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<LoginValues>({ resolver: zodResolver(loginSchema) });

  // On success the session changes and the AnonymousOnly guard navigates onward.
  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await login.mutateAsync(values);
    } catch (error) {
      setFormError(applyApiError(error, setError, ["email", "password"]));
    }
  });

  return (
    <>
      <h1>Sign in</h1>
      {params.get("reset") === "done" && (
        <Notice kind="ok">Your password has been changed. Sign in with the new one.</Notice>
      )}
      <form onSubmit={(event) => void onSubmit(event)} noValidate>
        {formError && <Notice kind="error">{formError}</Notice>}
        <TextField
          label="Email"
          type="email"
          autoComplete="email"
          error={errors.email?.message}
          {...register("email")}
        />
        <TextField
          label="Password"
          type="password"
          autoComplete="current-password"
          error={errors.password?.message}
          {...register("password")}
        />
        <button type="submit" className="primary" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="form-links">
        <Link to="/forgot-password">Forgot your password?</Link>
        <Link to={{ pathname: "/register", search: params.toString() }}>Create an account</Link>
      </p>
    </>
  );
}
