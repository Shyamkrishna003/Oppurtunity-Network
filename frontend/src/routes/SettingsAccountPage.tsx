import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Avatar } from "../components/Avatar";
import { TextField } from "../components/Field";
import { Notice } from "../components/Notice";
import { useChangePassword, useMe } from "../features/auth/api";
import { ResendVerification } from "../features/auth/ResendVerification";
import { changePasswordSchema, type ChangePasswordValues } from "../features/auth/schemas";
import { useBlockedUsers, useSetBlocked } from "../features/profile/api";
import { applyApiError, errorMessage } from "../services/formErrors";

function ChangePasswordForm() {
  const change = useChangePassword();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors },
  } = useForm<ChangePasswordValues>({ resolver: zodResolver(changePasswordSchema) });

  const onSubmit = handleSubmit(async ({ current_password, new_password }) => {
    setFormError(null);
    try {
      await change.mutateAsync({ current_password, new_password });
      reset();
    } catch (error) {
      setFormError(applyApiError(error, setError, ["current_password", "new_password"]));
    }
  });

  return (
    <form onSubmit={(event) => void onSubmit(event)} noValidate>
      {formError && <Notice kind="error">{formError}</Notice>}
      {change.isSuccess && (
        <Notice kind="ok">Password changed. You have been signed out on your other devices.</Notice>
      )}
      <TextField
        label="Current password"
        type="password"
        autoComplete="current-password"
        error={errors.current_password?.message}
        {...register("current_password")}
      />
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
      <button type="submit" className="primary" disabled={change.isPending}>
        {change.isPending ? "Saving…" : "Change password"}
      </button>
    </form>
  );
}

function BlockedUsers() {
  const blocked = useBlockedUsers();
  const setBlocked = useSetBlocked();

  if (blocked.isPending) {
    return (
      <p className="muted" role="status">
        Loading…
      </p>
    );
  }
  if (blocked.isError) {
    return (
      <Notice kind="error">
        <p>{errorMessage(blocked.error)}</p>
        <button type="button" onClick={() => void blocked.refetch()}>
          Try again
        </button>
      </Notice>
    );
  }
  if (blocked.data.results.length === 0) {
    return <p className="muted">You have not blocked anyone.</p>;
  }
  return (
    <>
      {setBlocked.isError && <Notice kind="error">{errorMessage(setBlocked.error)}</Notice>}
      <ul className="entry-list">
        {blocked.data.results.map((user) => (
          <li key={user.id} className="entry">
            <span className="person">
              <Avatar name={user.display_name} url={user.avatar_url} size={32} />
              {user.display_name}
            </span>
            <button
              type="button"
              disabled={setBlocked.isPending}
              onClick={() => setBlocked.mutate({ userId: user.id, blocked: false })}
            >
              Unblock<span className="visually-hidden"> {user.display_name}</span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

export function SettingsAccountPage() {
  const me = useMe();

  return (
    <>
      <h1>Account</h1>
      <section className="card" aria-labelledby="email-heading">
        <h2 id="email-heading">Email</h2>
        {me.data ? (
          <>
            <p>
              {me.data.email}{" "}
              <span className={me.data.email_verified ? "badge badge-ok" : "badge badge-error"}>
                {me.data.email_verified ? "Confirmed" : "Not confirmed"}
              </span>
            </p>
            {!me.data.email_verified && <ResendVerification email={me.data.email} />}
          </>
        ) : (
          <p className="muted" role="status">
            Loading…
          </p>
        )}
      </section>
      <section className="card" aria-labelledby="password-heading">
        <h2 id="password-heading">Password</h2>
        <ChangePasswordForm />
      </section>
      <section className="card" aria-labelledby="blocked-heading">
        <h2 id="blocked-heading">Blocked people</h2>
        <BlockedUsers />
      </section>
    </>
  );
}
