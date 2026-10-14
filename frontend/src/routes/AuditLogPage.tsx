import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { AuditTrail } from "../features/audit/AuditTrail";
import type { AuditFilters } from "../features/audit/api";

const FIELDS = ["actor_email", "action", "target_id"] as const;

/** The whole audit trail, for the platform's admins. What it is narrowed by lives in the
 *  address, so a search can be bookmarked or sent to a colleague. */
export function AuditLogPage() {
  const [params, setParams] = useSearchParams();
  const applied: AuditFilters = {
    actor_email: params.get("actor_email") ?? "",
    action: params.get("action") ?? "",
    target_id: params.get("target_id") ?? "",
  };
  // What is typed is only searched for once the form is sent.
  const [draft, setDraft] = useState(applied);
  const narrowed = FIELDS.some((field) => applied[field]);

  const field = (name: keyof AuditFilters, label: string, hint: string) => (
    <div className="field">
      <label htmlFor={`audit-${name}`}>{label}</label>
      <input
        id={`audit-${name}`}
        type={name === "actor_email" ? "email" : "text"}
        aria-describedby={`audit-${name}-hint`}
        value={draft[name]}
        onChange={(event) => setDraft({ ...draft, [name]: event.target.value })}
      />
      <p id={`audit-${name}-hint`} className="field-hint">
        {hint}
      </p>
    </div>
  );

  return (
    <>
      <p>
        <Link to="/admin">Admin</Link>
      </p>
      <h1>Audit log</h1>
      <p className="muted">
        Every recorded action on the platform, newest first. Nothing here can be changed.
      </p>
      <section className="card" aria-labelledby="narrow-heading">
        <h2 id="narrow-heading">Narrow it down</h2>
        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            const given = FIELDS.map((name) => [name, draft[name].trim()] as const);
            setParams(Object.fromEntries(given.filter(([, value]) => value)));
          }}
        >
          {field("actor_email", "Done by", "Their email address, in full.")}
          {field("action", "Action", 'A whole action, or the start of one: "report."')}
          {field("target_id", "Done to", "The id of the person or thing, from its address.")}
          <div className="button-row">
            <button type="submit" className="primary">
              Search
            </button>
            {narrowed && (
              <button
                type="button"
                onClick={() => {
                  setDraft({ actor_email: "", action: "", target_id: "" });
                  setParams({});
                }}
              >
                Show everything
              </button>
            )}
          </div>
        </form>
      </section>
      <section className="card" aria-label="Records">
        <AuditTrail
          scope={{ kind: "platform", filters: applied }}
          forWhom="the platform's admins"
        />
      </section>
    </>
  );
}
