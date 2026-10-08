import { useId, useState } from "react";

import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { errorMessage } from "../../services/formErrors";
import type { Skill } from "../auth/types";
import { useCreateSkill, useSkillSuggestions } from "./api";

interface SkillPickerProps {
  label: string;
  value: Skill[];
  onChange: (skills: Skill[]) => void;
  max?: number;
  /** Adding a skill that is not in the list yet needs a confirmed email address. */
  canCreate: boolean;
}

export function SkillPicker({ label, value, onChange, max = 50, canCreate }: SkillPickerProps) {
  const inputId = useId();
  const [text, setText] = useState("");
  const typed = text.trim();
  const query = useDebouncedValue(typed, 200);
  const suggestions = useSkillSuggestions(query);
  const create = useCreateSkill();

  const selected = new Set(value.map((skill) => skill.id));
  const matches = typed && query ? (suggestions.data ?? []) : [];
  const options = matches.filter((skill) => !selected.has(skill.id));
  const full = value.length >= max;
  // Offer "add" only once the results shown are for exactly what is typed.
  const settled = typed !== "" && typed === query && suggestions.isSuccess;
  const hasExactMatch = matches.some((skill) => skill.name.toLowerCase() === typed.toLowerCase());

  function add(skill: Skill) {
    if (!selected.has(skill.id) && !full) {
      onChange([...value, skill]);
    }
    setText("");
    create.reset();
  }

  return (
    <div className="field">
      <label htmlFor={inputId}>{label}</label>
      {value.length > 0 && (
        <ul className="chips" aria-label={`${label}: selected`}>
          {value.map((skill) => (
            <li key={skill.id} className="chip">
              {skill.name}
              <button
                type="button"
                className="chip-remove"
                aria-label={`Remove ${skill.name}`}
                onClick={() => onChange(value.filter((other) => other.id !== skill.id))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <input
        id={inputId}
        type="text"
        value={text}
        maxLength={60}
        autoComplete="off"
        disabled={full}
        placeholder={full ? `Limit of ${max} reached` : "Type to search, e.g. React"}
        onChange={(event) => setText(event.target.value)}
      />
      {suggestions.isError && typed && (
        <p className="field-error" role="alert">
          Suggestions could not be loaded.
        </p>
      )}
      {options.length > 0 && (
        <ul className="suggestions" aria-label={`${label}: suggestions`}>
          {options.map((skill) => (
            <li key={skill.id}>
              <button type="button" onClick={() => add(skill)}>
                {skill.name}
              </button>
            </li>
          ))}
        </ul>
      )}
      {settled && !hasExactMatch && (
        <p className="field-hint">
          {options.length === 0 && "No matching skill. "}
          {canCreate ? (
            <button
              type="button"
              className="link"
              disabled={create.isPending}
              onClick={() => create.mutate(typed, { onSuccess: add })}
            >
              Add “{typed}”
            </button>
          ) : (
            "Confirm your email address to add new skills."
          )}
        </p>
      )}
      {create.isError && (
        <p className="field-error" role="alert">
          {errorMessage(create.error)}
        </p>
      )}
    </div>
  );
}
