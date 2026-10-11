import { Link } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useMe } from "../features/auth/api";
import { usePreferences, useSavePreferences } from "../features/notifications/api";
import type { NotificationPreference } from "../features/notifications/types";
import { errorMessage } from "../services/formErrors";

export function SettingsNotificationsPage() {
  const me = useMe();
  const preferences = usePreferences();
  const save = useSavePreferences();

  if (preferences.isPending) {
    return <Splash />;
  }
  if (preferences.isError) {
    return (
      <>
        <h1>Notification settings</h1>
        <Notice kind="error">
          <p>{errorMessage(preferences.error)}</p>
          <button type="button" onClick={() => void preferences.refetch()}>
            Try again
          </button>
        </Notice>
      </>
    );
  }

  // Each switch saves on its own: only the category that changed is sent.
  function set(preference: NotificationPreference, change: { in_app?: boolean; email?: boolean }) {
    save.mutate([
      {
        category: preference.category,
        in_app: change.in_app ?? preference.in_app,
        email: change.email ?? preference.email,
      },
    ]);
  }

  return (
    <>
      <h1>Notification settings</h1>
      <p className="muted">
        Choose where you hear about each kind of thing. Emails go to{" "}
        {me.data?.email ?? "your address"}
        {me.data && !me.data.email_verified && ", once you have confirmed it"}.
      </p>
      {save.isError && <Notice kind="error">{errorMessage(save.error)}</Notice>}
      {save.isSuccess && <Notice kind="ok">Saved.</Notice>}

      <section className="card" aria-label="Notification settings">
        <table className="preferences">
          <thead>
            <tr>
              <th scope="col">Tell me about</th>
              <th scope="col">In the app</th>
              <th scope="col">By email</th>
            </tr>
          </thead>
          <tbody>
            {preferences.data.map((preference) => (
              <tr key={preference.category}>
                <th scope="row">
                  {preference.title}
                  <div className="field-hint">{preference.description}</div>
                </th>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`${preference.title}: in the app`}
                    checked={preference.in_app}
                    disabled={save.isPending}
                    onChange={(event) => set(preference, { in_app: event.target.checked })}
                  />
                </td>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`${preference.title}: by email`}
                    checked={preference.email}
                    disabled={save.isPending}
                    onChange={(event) => set(preference, { email: event.target.checked })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="field-hint">
          Invitations are always emailed to the invited address, whatever is chosen here.
        </p>
      </section>
      <p className="form-links">
        <Link to="/notifications">Back to notifications</Link>
      </p>
    </>
  );
}
