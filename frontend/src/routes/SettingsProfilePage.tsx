import { Link } from "react-router";

import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import { useMe } from "../features/auth/api";
import { AvatarEditor } from "../features/profile/AvatarEditor";
import { BasicsForm } from "../features/profile/BasicsForm";
import { HistoryEditor } from "../features/profile/HistoryEditor";
import { PrivacyForm } from "../features/profile/PrivacyForm";
import { SkillsEditor } from "../features/profile/SkillsEditor";
import { errorMessage } from "../services/formErrors";

export function SettingsProfilePage() {
  const me = useMe();

  if (me.isPending) {
    return <Splash />;
  }
  if (me.isError) {
    return (
      <Notice kind="error">
        <p>{errorMessage(me.error)}</p>
        <button type="button" onClick={() => void me.refetch()}>
          Try again
        </button>
      </Notice>
    );
  }

  const user = me.data;
  return (
    <>
      <h1>Edit profile</h1>
      <p className="muted">
        <Link to={`/users/${user.id}`}>View my profile</Link>
      </p>
      <section className="card" aria-labelledby="photo-heading">
        <h2 id="photo-heading">Photo</h2>
        <AvatarEditor profile={user.profile} />
      </section>
      <section className="card" aria-labelledby="basics-heading">
        <h2 id="basics-heading">About you</h2>
        <BasicsForm profile={user.profile} />
      </section>
      <section className="card" aria-labelledby="skills-heading">
        <h2 id="skills-heading">Skills and interests</h2>
        <p className="muted">These decide which opportunities are shown to you first.</p>
        <SkillsEditor me={user} />
      </section>
      <section className="card" aria-labelledby="experience-heading">
        <h2 id="experience-heading">Experience</h2>
        <HistoryEditor kind="experiences" />
      </section>
      <section className="card" aria-labelledby="education-heading">
        <h2 id="education-heading">Education</h2>
        <HistoryEditor kind="educations" />
      </section>
      <section className="card" aria-labelledby="privacy-heading">
        <h2 id="privacy-heading">Privacy</h2>
        <PrivacyForm profile={user.profile} />
      </section>
    </>
  );
}
