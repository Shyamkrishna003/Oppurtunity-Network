import { useId, type ComponentProps, type ReactNode } from "react";

interface FieldShellProps {
  label: string;
  error?: string;
  hint?: string;
  children: (ids: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode;
}

function FieldShell({ label, error, hint, children }: FieldShellProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint && hintId, error && errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children({ id, describedBy, invalid: Boolean(error) })}
      {hint && (
        <p id={hintId} className="field-hint">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

type Common = { label: string; error?: string; hint?: string };

export function TextField({ label, error, hint, ...input }: Common & ComponentProps<"input">) {
  return (
    <FieldShell label={label} error={error} hint={hint}>
      {({ id, describedBy, invalid }) => (
        <input id={id} aria-describedby={describedBy} aria-invalid={invalid} {...input} />
      )}
    </FieldShell>
  );
}

export function TextAreaField({
  label,
  error,
  hint,
  ...textarea
}: Common & ComponentProps<"textarea">) {
  return (
    <FieldShell label={label} error={error} hint={hint}>
      {({ id, describedBy, invalid }) => (
        <textarea id={id} aria-describedby={describedBy} aria-invalid={invalid} {...textarea} />
      )}
    </FieldShell>
  );
}

export function SelectField({
  label,
  error,
  hint,
  children,
  ...select
}: Common & ComponentProps<"select">) {
  return (
    <FieldShell label={label} error={error} hint={hint}>
      {({ id, describedBy, invalid }) => (
        <select id={id} aria-describedby={describedBy} aria-invalid={invalid} {...select}>
          {children}
        </select>
      )}
    </FieldShell>
  );
}

export function CheckboxField({
  label,
  hint,
  ...input
}: { label: string; hint?: string } & ComponentProps<"input">) {
  const id = useId();
  return (
    <div className="field field-checkbox">
      <input
        id={id}
        type="checkbox"
        aria-describedby={hint ? `${id}-hint` : undefined}
        {...input}
      />
      <div>
        <label htmlFor={id}>{label}</label>
        {hint && (
          <p id={`${id}-hint`} className="field-hint">
            {hint}
          </p>
        )}
      </div>
    </div>
  );
}
