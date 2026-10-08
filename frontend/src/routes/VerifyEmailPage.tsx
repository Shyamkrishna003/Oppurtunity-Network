import { Link, useSearchParams } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useMe, useSessionStatus, useVerifyEmail } from "../features/auth/api";
import { ResendVerification } from "../features/auth/ResendVerification";
import { errorMessage } from "../services/formErrors";

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const verification = useVerifyEmail(token);
  const status = useSessionStatus();
  const me = useMe();
  const signedIn = status === "authenticated";

  if (!token) {
    return (
      <>
        <h1>Confirm your email</h1>
        <Notice kind="error">This link is incomplete. Open the link from your email again.</Notice>
        <Link to="/">Back to home</Link>
      </>
    );
  }
  if (verification.isPending) {
    return <Splash label="Confirming your email address…" />;
  }
  if (verification.isError) {
    return (
      <>
        <h1>Confirm your email</h1>
        <Notice kind="error">{errorMessage(verification.error)}</Notice>
        {me.data && !me.data.email_verified ? (
          <ResendVerification email={me.data.email} />
        ) : (
          <p className="muted">Sign in to request a new link.</p>
        )}
        <p className="form-links">
          <Link to={signedIn ? "/" : "/login"}>{signedIn ? "Back to home" : "Go to sign in"}</Link>
        </p>
      </>
    );
  }
  return (
    <>
      <h1>Email confirmed</h1>
      <Notice kind="ok">Your email address is confirmed.</Notice>
      <Link to={signedIn ? "/" : "/login"}>{signedIn ? "Continue" : "Sign in"}</Link>
    </>
  );
}
