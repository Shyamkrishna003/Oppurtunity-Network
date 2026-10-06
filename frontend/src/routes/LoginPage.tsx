import { Link } from "react-router";

export function LoginPage() {
  return (
    <>
      <h1>Sign in</h1>
      <p className="muted">Accounts are not available yet.</p>
      <Link to="/">Back to home</Link>
    </>
  );
}
