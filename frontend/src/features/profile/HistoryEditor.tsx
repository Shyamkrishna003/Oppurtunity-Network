import { useState } from "react";
import { useForm } from "react-hook-form";

import { TextAreaField, TextField } from "../../components/Field";
import { Notice } from "../../components/Notice";
import { applyApiError, errorMessage } from "../../services/formErrors";
import { useDeleteHistoryEntry, useHistory, useSaveHistoryEntry, type HistoryKind } from "./api";
import { formatPeriod } from "./labels";
import type { Education, Experience } from "./types";

interface FieldSpec {
  name: string;
  label: string;
  required?: boolean;
  type?: "text" | "date" | "textarea";
  maxLength?: number;
}

interface KindSpec {
  noun: string;
  empty: string;
  fields: FieldSpec[];
  summary: (entry: Experience & Education) => { title: string; subtitle: string };
}

const DATES: FieldSpec[] = [
  { name: "start_date", label: "Start date", type: "date", required: true },
  { name: "end_date", label: "End date (leave empty if current)", type: "date" },
];

const SPECS: Record<HistoryKind, KindSpec> = {
  experiences: {
    noun: "experience",
    empty: "No experience added yet.",
    fields: [
      { name: "title", label: "Title", required: true, maxLength: 120 },
      { name: "organization_name", label: "Organization", required: true, maxLength: 120 },
      ...DATES,
      { name: "description", label: "Description", type: "textarea", maxLength: 2000 },
    ],
    summary: (entry) => ({ title: entry.title, subtitle: entry.organization_name }),
  },
  educations: {
    noun: "education",
    empty: "No education added yet.",
    fields: [
      { name: "institution", label: "Institution", required: true, maxLength: 160 },
      { name: "degree", label: "Degree", maxLength: 120 },
      { name: "field_of_study", label: "Field of study", maxLength: 120 },
      ...DATES,
    ],
    summary: (entry) => ({
      title: entry.institution,
      subtitle: [entry.degree, entry.field_of_study].filter(Boolean).join(", "),
    }),
  },
};

type Entry = { id: string; start_date: string; end_date: string | null } & Record<string, unknown>;
type Values = Record<string, string>;

function EntryForm({
  kind,
  entry,
  onDone,
}: {
  kind: HistoryKind;
  entry: Entry | null;
  onDone: () => void;
}) {
  const spec = SPECS[kind];
  const save = useSaveHistoryEntry(kind);
  const [formError, setFormError] = useState<string | null>(null);
  const defaults = Object.fromEntries(
    spec.fields.map((field) => [field.name, String(entry?.[field.name] ?? "")]),
  );
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<Values>({ defaultValues: defaults });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const body = { ...values, end_date: values.end_date || null, id: entry?.id };
      await save.mutateAsync(body as never);
      onDone();
    } catch (error) {
      setFormError(
        applyApiError(
          error,
          setError,
          spec.fields.map((field) => field.name),
        ),
      );
    }
  });

  return (
    <form onSubmit={(event) => void onSubmit(event)} noValidate className="entry-form">
      {formError && <Notice kind="error">{formError}</Notice>}
      {spec.fields.map((field) => {
        const props = {
          label: field.label,
          error: errors[field.name]?.message,
          maxLength: field.maxLength,
          ...register(field.name, {
            required: field.required ? `${field.label} is required.` : false,
          }),
        };
        return field.type === "textarea" ? (
          <TextAreaField key={field.name} rows={3} {...props} />
        ) : (
          <TextField key={field.name} type={field.type ?? "text"} {...props} />
        );
      })}
      <div className="button-row">
        <button type="submit" className="primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={onDone} disabled={save.isPending}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** List with inline add, edit and delete for the signed-in user's experience or education. */
export function HistoryEditor({ kind }: { kind: HistoryKind }) {
  const spec = SPECS[kind];
  const entries = useHistory(kind);
  const remove = useDeleteHistoryEntry(kind);
  const [editing, setEditing] = useState<string | "new" | null>(null);

  if (entries.isPending) {
    return (
      <p className="muted" role="status">
        Loading…
      </p>
    );
  }
  if (entries.isError) {
    return (
      <Notice kind="error">
        <p>{errorMessage(entries.error)}</p>
        <button type="button" onClick={() => void entries.refetch()}>
          Try again
        </button>
      </Notice>
    );
  }

  const list = entries.data as unknown as Entry[];
  return (
    <>
      {remove.isError && <Notice kind="error">{errorMessage(remove.error)}</Notice>}
      {list.length === 0 && editing !== "new" && <p className="muted">{spec.empty}</p>}
      <ul className="entry-list">
        {list.map((entry) => {
          const { title, subtitle } = spec.summary(entry as never);
          return (
            <li key={entry.id}>
              {editing === entry.id ? (
                <EntryForm kind={kind} entry={entry} onDone={() => setEditing(null)} />
              ) : (
                <div className="entry">
                  <div>
                    <strong>{title}</strong>
                    {subtitle && <div>{subtitle}</div>}
                    <div className="muted">{formatPeriod(entry.start_date, entry.end_date)}</div>
                  </div>
                  <div className="button-row">
                    <button type="button" onClick={() => setEditing(entry.id)}>
                      Edit<span className="visually-hidden"> {title}</span>
                    </button>
                    <button
                      type="button"
                      disabled={remove.isPending}
                      onClick={() => {
                        if (window.confirm(`Delete “${title}”?`)) {
                          remove.mutate(entry.id);
                        }
                      }}
                    >
                      Delete<span className="visually-hidden"> {title}</span>
                    </button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {editing === "new" ? (
        <EntryForm kind={kind} entry={null} onDone={() => setEditing(null)} />
      ) : (
        <button type="button" onClick={() => setEditing("new")}>
          Add {spec.noun}
        </button>
      )}
    </>
  );
}
