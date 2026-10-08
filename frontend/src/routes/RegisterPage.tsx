import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router";

import { TextField } from "../components/Field";
import { Notice } from "../components/Notice";
import { useRegister } from "../features/auth/api";
import { registerSchema, type RegisterValues } from "../features/auth/schemas";
import { applyApiError } from "../services/formErrors";

export function RegisterPage() {
  const signUp = useRegister();
  const [formError, setFormError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<RegisterValues>({ resolver: zodResolver(registerSchema) });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await signUp.mutateAsync(values);
      setSentTo(values.email);
    } catch (error) {
      setFormError(applyApiError(error, setError, ["display_name", "email", "password"]));
    }
  });

  if (sentTo) {
    return (
      <>
        <h1>Check your email</h1>
        <p>
          We sent a message to <strong>{sentTo}</strong>. Open the link in it to confirm your
          address, then sign in.
        </p>
        <p className="muted">
          Nothing after a few minutes? Check your spam folder, or sign in and request a new link.
        </p>
        <Link to="/login">Go to sign in</Link>
      </>
    );
  }

  return (
    <>
      <h1>Create an account</h1>
      <form onSubmit={(event) => void onSubmit(event)} noValidate>
        {formError && <Notice kind="error">{formError}</Notice>}
        <TextField
          label="Name"
          autoComplete="name"
          error={errors.display_name?.message}
          {...register("display_name")}
        />
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
          autoComplete="new-password"
          hint="At least 10 characters."
          error={errors.password?.message}
          {...register("password")}
        />
        <button type="submit" className="primary" disabled={signUp.isPending}>
          {signUp.isPending ? "Creating account…" : "Create account"}
        </button>
      </form>
      <p className="form-links">
        <Link to="/login">Already have an account? Sign in</Link>
      </p>
    </>
  );
}
