import { useState } from "react";

import { TextAreaField, TextField } from "../../components/Field";
import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { useReplaceRules } from "./api";
import type { CommunityDetail, Rule } from "./types";

const MAX_RULES = 20;

/** Edit the whole ordered list of rules and save it in one request. */
export function RulesEditor({
  community,
  onDone,
}: {
  community: CommunityDetail;
  onDone: () => void;
}) {
  const save = useReplaceRules(community.id);
  const [rules, setRules] = useState<Rule[]>(community.rules);
  const untitled = rules.some((rule) => rule.title.trim() === "");

  function update(index: number, change: Partial<Rule>) {
    setRules(rules.map((rule, i) => (i === index ? { ...rule, ...change } : rule)));
  }

  function move(index: number, by: -1 | 1) {
    const next = [...rules];
    const [rule] = next.splice(index, 1);
    if (rule) {
      next.splice(index + by, 0, rule);
      setRules(next);
    }
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        const cleaned = rules.map((rule) => ({
          title: rule.title.trim(),
          body: rule.body.trim(),
        }));
        save.mutate(cleaned, { onSuccess: onDone });
      }}
    >
      {save.isError && <Notice kind="error">{errorMessage(save.error)}</Notice>}
      {rules.length === 0 && <p className="muted">No rules yet.</p>}
      <ol className="rule-editor">
        {rules.map((rule, index) => (
          // Rules have no identity of their own; their position is what is being edited.
          <li key={index}>
            <TextField
              label={`Rule ${index + 1}`}
              value={rule.title}
              maxLength={120}
              onChange={(event) => update(index, { title: event.target.value })}
            />
            <TextAreaField
              label={`Details for rule ${index + 1} (optional)`}
              rows={2}
              value={rule.body}
              maxLength={2000}
              onChange={(event) => update(index, { body: event.target.value })}
            />
            <div className="button-row">
              <button type="button" disabled={index === 0} onClick={() => move(index, -1)}>
                Move up <span className="visually-hidden">rule {index + 1}</span>
              </button>
              <button
                type="button"
                disabled={index === rules.length - 1}
                onClick={() => move(index, 1)}
              >
                Move down <span className="visually-hidden">rule {index + 1}</span>
              </button>
              <button type="button" onClick={() => setRules(rules.filter((_, i) => i !== index))}>
                Delete <span className="visually-hidden">rule {index + 1}</span>
              </button>
            </div>
          </li>
        ))}
      </ol>
      <div className="button-row">
        <button
          type="button"
          disabled={rules.length >= MAX_RULES}
          onClick={() => setRules([...rules, { title: "", body: "" }])}
        >
          Add rule
        </button>
        <button type="submit" className="primary" disabled={save.isPending || untitled}>
          {save.isPending ? "Saving…" : "Save rules"}
        </button>
        <button type="button" onClick={onDone} disabled={save.isPending}>
          Cancel
        </button>
      </div>
      {untitled && <p className="field-hint">Give every rule a title, or delete it.</p>}
    </form>
  );
}
