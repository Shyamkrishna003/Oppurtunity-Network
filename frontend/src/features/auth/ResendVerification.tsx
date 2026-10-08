import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { useResendVerification } from "./api";

/** Button that emails a fresh confirmation link to the given address. */
export function ResendVerification({ email }: { email: string }) {
  const resend = useResendVerification();

  if (resend.isSuccess) {
    return <Notice kind="ok">A new link is on its way to {email}.</Notice>;
  }
  return (
    <>
      {resend.isError && <Notice kind="error">{errorMessage(resend.error)}</Notice>}
      <button type="button" onClick={() => resend.mutate(email)} disabled={resend.isPending}>
        {resend.isPending ? "Sending…" : "Send a new link"}
      </button>
    </>
  );
}
