import { Link } from "react-router";

import { Icon, type IconName } from "../components/Icon";
import { Splash } from "../components/Splash";
import { useMe, useSessionStatus } from "../features/auth/api";
import { useFeed } from "../features/opportunities/api";
import { MatchReasons } from "../features/opportunities/MatchReasons";
import { OpportunityCard } from "../features/opportunities/OpportunityCard";
import { SaveButton } from "../features/opportunities/SaveButton";

const SHORTCUTS: { to: string; icon: IconName; title: string; hint: string }[] = [
  {
    to: "/opportunities?sort=relevant",
    icon: "spark",
    title: "Best matches",
    hint: "Ranked by your skills",
  },
  {
    to: "/applications",
    icon: "briefcase",
    title: "Track applications",
    hint: "See where each one stands",
  },
  { to: "/communities", icon: "people", title: "Find your people", hint: "Join a community" },
  {
    to: "/opportunities/new",
    icon: "megaphone",
    title: "Post a job",
    hint: "Reach the right crowd",
  },
];

/** A few opportunities to start scrolling from: the best matches for someone signed in,
 *  the newest for a visitor. Says nothing at all if they cannot be loaded. */
function Picks({ signedIn }: { signedIn: boolean }) {
  const all = signedIn ? "/opportunities?sort=relevant" : "/opportunities";
  const feed = useFeed(signedIn ? "sort=relevant&page_size=4" : "page_size=4");
  const picks = feed.data?.pages[0]?.results ?? [];

  if (feed.isError) {
    return null;
  }
  return (
    <section aria-labelledby="picks-heading">
      <div className="section-heading">
        <h2 id="picks-heading">{signedIn ? "Picked for you" : "Fresh on the network"}</h2>
        <Link to={all}>See all opportunities</Link>
      </div>
      {feed.isPending && <Splash label="Finding good ones…" />}
      {feed.isSuccess && picks.length === 0 && (
        <p className="muted">Nothing has been published yet. Check back soon.</p>
      )}
      {picks.length > 0 && (
        <div className="feed">
          <ul className="entry-list">
            {picks.map((item) => (
              <OpportunityCard
                key={item.id}
                opportunity={item}
                actions={<SaveButton id={item.id} title={item.title} saved={item.is_saved} />}
              >
                <MatchReasons match={item.match} />
              </OpportunityCard>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

export function HomePage() {
  const status = useSessionStatus();
  const me = useMe();

  if (status === "unknown") {
    return <Splash />;
  }
  if (status === "anonymous") {
    return (
      <>
        <section className="hero">
          <h1>Your next opportunity is already in your circle.</h1>
          <p>Jobs, events and referrals, shared through the communities you trust.</p>
          <div className="button-row">
            <Link to="/register" className="button primary">
              Create an account
            </Link>
            <Link to="/opportunities" className="button">
              Browse opportunities
            </Link>
          </div>
        </section>
        <Picks signedIn={false} />
      </>
    );
  }
  return (
    <>
      <section className="hero">
        <h1>
          {me.data ? `Welcome, ${me.data.profile.display_name}` : "Welcome"}{" "}
          <span className="wave" aria-hidden="true">
            👋
          </span>
        </h1>
        <p>
          Opportunities are ranked by your skills, interests and location.{" "}
          <Link to="/settings/profile">Keep your profile fresh</Link> to see the right ones first.
        </p>
      </section>
      <ul className="tiles" aria-label="Shortcuts">
        {SHORTCUTS.map((shortcut) => (
          <li key={shortcut.to}>
            <Link to={shortcut.to} className="tile">
              <Icon name={shortcut.icon} size={26} />
              {shortcut.title}
              <small>{shortcut.hint}</small>
            </Link>
          </li>
        ))}
      </ul>
      <Picks signedIn />
    </>
  );
}
