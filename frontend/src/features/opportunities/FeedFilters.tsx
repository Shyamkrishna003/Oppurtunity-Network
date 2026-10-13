import type { FormEvent } from "react";

import { CheckboxField } from "../../components/Field";
import { EXPERIENCE_LEVELS, WORK_MODES } from "../profile/labels";
import { SkillPicker } from "../profile/SkillPicker";
import { useSkillsById } from "./api";
import { FEED_PARAMS } from "./feedParams";
import { EMPLOYMENT_TYPE_LABELS, SORT_LABELS, type FeedSort } from "./types";

const POSTED_WITHIN: Record<string, string> = {
  "1": "The last day",
  "7": "The last week",
  "30": "The last month",
};

interface FeedFiltersProps {
  params: URLSearchParams;
  /** Replace some parameters; null or an empty value removes one. */
  onChange: (changes: Record<string, string | string[] | null>) => void;
  onClear: () => void;
  signedIn: boolean;
}

function options(labels: Record<string, string>) {
  return Object.entries(labels).map(([value, label]) => (
    <option key={value} value={value}>
      {label}
    </option>
  ));
}

export function FeedFilters({ params, onChange, onClear, signedIn }: FeedFiltersProps) {
  const skillIds = params.getAll("skill");
  const skills = useSkillsById(signedIn ? skillIds : []);
  const q = params.get("q") ?? "";
  const city = params.get("city") ?? "";
  const country = params.get("country") ?? "";
  // A search is ordered by best match unless another order is chosen; browsing, by date.
  const sort = (params.get("sort") as FeedSort | null) ?? (q ? "relevant" : "newest");
  const filtered = FEED_PARAMS.some((name) => name !== "sort" && params.has(name));
  // How many of the folded-away filters are in use (the search box and the order are not).
  const narrowed = new Set(
    [...params.keys()].filter(
      (name) =>
        name !== "sort" && name !== "q" && (FEED_PARAMS as readonly string[]).includes(name),
    ),
  ).size;

  function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim();
    onChange({ q: text("q"), city: text("city"), country: text("country").toUpperCase() });
  }

  const select = (name: string, label: string, labels: Record<string, string>, any: string) => (
    <div className="field">
      <label htmlFor={`filter-${name}`}>{label}</label>
      <select
        id={`filter-${name}`}
        value={params.get(name) ?? ""}
        onChange={(event) => onChange({ [name]: event.target.value })}
      >
        <option value="">{any}</option>
        {options(labels)}
      </select>
    </div>
  );

  return (
    <section className="card" aria-label="Search and filters">
      {/* Keyed by what it shows, so the boxes follow the address on back and forward. */}
      <form
        id="feed-search"
        key={`${q}|${city}|${country}`}
        role="search"
        className="search-form"
        onSubmit={onSearch}
      >
        <input
          type="search"
          name="q"
          defaultValue={q}
          maxLength={120}
          aria-label="Search opportunities"
          placeholder="Search by title, skill, organization or place"
        />
        <button type="submit" className="primary">
          Search
        </button>
      </form>

      {/* Folded away so the opportunities start near the top; open whenever one is in use. */}
      <details className="filters" open={narrowed > 0}>
        <summary>
          Filters
          {narrowed > 0 && <span className="filters-count">{narrowed}</span>}
        </summary>
        {/* Outside the search form in the page, but sent with it. */}
        <div className="field-row" key={`${city}|${country}`}>
          <div className="field">
            <label htmlFor="filter-city">City</label>
            <input
              id="filter-city"
              form="feed-search"
              name="city"
              defaultValue={city}
              maxLength={80}
            />
          </div>
          <div className="field">
            <label htmlFor="filter-country">Country code</label>
            <input
              id="filter-country"
              form="feed-search"
              name="country"
              defaultValue={country}
              maxLength={2}
              pattern="[A-Za-z]{2}"
              placeholder="IN"
            />
          </div>
        </div>

        <div className="field-row">
          {select("type", "Type", { JOB: "Jobs", EVENT: "Events" }, "Jobs and events")}
          {select("work_mode", "Work mode", WORK_MODES, "Any")}
          {select("experience_level", "Experience", EXPERIENCE_LEVELS, "Any")}
          {select("employment_type", "Employment type", EMPLOYMENT_TYPE_LABELS, "Any")}
          {select("posted_within", "Posted", POSTED_WITHIN, "Any time")}
        </div>

        {signedIn && (
          <>
            <SkillPicker
              label="Needs any of these skills"
              value={skills.data ?? []}
              onChange={(chosen) => onChange({ skill: chosen.map((skill) => skill.id) })}
              max={15}
              canCreate={false}
              existingOnly
            />
            <CheckboxField
              label="Only from communities I belong to"
              checked={params.get("scope") === "communities"}
              onChange={(event) => onChange({ scope: event.target.checked ? "communities" : null })}
            />
          </>
        )}
      </details>

      <div className="page-heading filters-foot">
        <div className="field">
          <label htmlFor="filter-sort">Order by</label>
          <select
            id="filter-sort"
            value={sort}
            onChange={(event) => onChange({ sort: event.target.value })}
          >
            {options(SORT_LABELS)}
          </select>
        </div>
        {filtered && (
          <button type="button" onClick={onClear}>
            Clear filters
          </button>
        )}
      </div>
    </section>
  );
}
