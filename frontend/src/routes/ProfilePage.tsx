import { Link, useNavigate, useParams } from "react-router";

import { Avatar } from "../components/Avatar";
import { Notice } from "../components/Notice";
import { Splash } from "../components/Splash";
import type { Skill } from "../features/auth/types";
import { useProfile, useSetBlocked } from "../features/profile/api";
import {
  EXPERIENCE_LEVELS,
  formatLocation,
  formatPeriod,
  WORK_MODES,
} from "../features/profile/labels";
import { errorMessage } from "../services/formErrors";
import { ApiError } from "../services/http";

function SkillList({ title, skills }: { title: string; skills: Skill[] }) {
  if (skills.length === 0) {
    return null;
  }
  return (
    <>
      <h3>{title}</h3>
      <ul className="chips">
        {skills.map((skill) => (
          <li key={skill.id} className="chip">
            {skill.name}
          </li>
        ))}
      </ul>
    </>
  );
}

export function ProfilePage() {
  const { userId = "" } = useParams();
  const navigate = useNavigate();
  const profile = useProfile(userId);
  const setBlocked = useSetBlocked();

  if (profile.isPending) {
    return <Splash />;
  }
  if (profile.isError) {
    const notFound = profile.error instanceof ApiError && profile.error.status === 404;
    return (
      <>
        <h1>{notFound ? "Profile not available" : "Something went wrong"}</h1>
        <p className="muted">
          {notFound
            ? "This profile does not exist or is not visible to you."
            : errorMessage(profile.error)}
        </p>
        {!notFound && (
          <button type="button" onClick={() => void profile.refetch()}>
            Try again
          </button>
        )}
      </>
    );
  }

  const user = profile.data;
  const location = formatLocation(user);
  const facts = [
    location,
    user.work_mode_preference && `Prefers ${WORK_MODES[user.work_mode_preference].toLowerCase()}`,
    user.experience_level && EXPERIENCE_LEVELS[user.experience_level],
  ].filter(Boolean);
  const noSkills = user.skills.has.length === 0 && user.skills.interested.length === 0;

  return (
    <>
      <header className="profile-header">
        <Avatar name={user.display_name} url={user.avatar_url} size={88} />
        <div>
          <h1>{user.display_name}</h1>
          {user.headline && <p>{user.headline}</p>}
          {facts.length > 0 && <p className="muted">{facts.join(" · ")}</p>}
          {user.email && (
            <p>
              <a href={`mailto:${user.email}`}>{user.email}</a>
            </p>
          )}
        </div>
        <div className="profile-actions">
          {user.is_self ? (
            <Link to="/settings/profile" className="button">
              Edit profile
            </Link>
          ) : (
            <button
              type="button"
              disabled={setBlocked.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    `Block ${user.display_name}? Neither of you will be able to open the other's profile.`,
                  )
                ) {
                  setBlocked.mutate(
                    { userId: user.id, blocked: true },
                    { onSuccess: () => void navigate("/settings/account") },
                  );
                }
              }}
            >
              Block
            </button>
          )}
        </div>
      </header>
      {setBlocked.isError && <Notice kind="error">{errorMessage(setBlocked.error)}</Notice>}

      {user.bio && (
        <section className="card" aria-labelledby="about-heading">
          <h2 id="about-heading">About</h2>
          <p className="prose">{user.bio}</p>
        </section>
      )}

      <section className="card" aria-labelledby="skills-heading">
        <h2 id="skills-heading">Skills</h2>
        {noSkills ? (
          <p className="muted">No skills listed yet.</p>
        ) : (
          <>
            <SkillList title="Has" skills={user.skills.has} />
            <SkillList title="Interested in" skills={user.skills.interested} />
          </>
        )}
      </section>

      {user.experiences && (
        <section className="card" aria-labelledby="experience-heading">
          <h2 id="experience-heading">Experience</h2>
          {user.experiences.length === 0 ? (
            <p className="muted">No experience listed yet.</p>
          ) : (
            <ul className="entry-list">
              {user.experiences.map((entry) => (
                <li key={entry.id}>
                  <strong>{entry.title}</strong>
                  <div>{entry.organization_name}</div>
                  <div className="muted">{formatPeriod(entry.start_date, entry.end_date)}</div>
                  {entry.description && <p className="prose">{entry.description}</p>}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {user.educations && (
        <section className="card" aria-labelledby="education-heading">
          <h2 id="education-heading">Education</h2>
          {user.educations.length === 0 ? (
            <p className="muted">No education listed yet.</p>
          ) : (
            <ul className="entry-list">
              {user.educations.map((entry) => (
                <li key={entry.id}>
                  <strong>{entry.institution}</strong>
                  <div>{[entry.degree, entry.field_of_study].filter(Boolean).join(", ")}</div>
                  <div className="muted">{formatPeriod(entry.start_date, entry.end_date)}</div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </>
  );
}
