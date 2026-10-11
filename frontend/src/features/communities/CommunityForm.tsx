import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { SelectField, TextAreaField, TextField } from "../../components/Field";
import { Notice } from "../../components/Notice";
import { applyApiError } from "../../services/formErrors";
import {
  JOIN_POLICY_LABELS,
  POSTING_POLICY_LABELS,
  VISIBILITY_LABELS,
  type CommunityFields,
} from "./types";

const schema = z.object({
  name: z.string().trim().min(1, "Enter the community's name.").max(120),
  description: z.string().trim().max(4000, "Use at most 4000 characters."),
  category: z.string().trim().max(60),
  join_policy: z.enum(["OPEN", "APPROVAL", "INVITE_ONLY"]),
  posting_policy: z.enum(["ADMINS_ONLY", "MEMBERS_WITH_APPROVAL", "MEMBERS_AUTO"]),
  visibility: z.enum(["PUBLIC", "PRIVATE"]),
});
type Values = z.infer<typeof schema>;
const FIELDS = Object.keys(schema.shape) as (keyof Values)[];

const DEFAULTS: Values = {
  name: "",
  description: "",
  category: "",
  join_policy: "OPEN",
  posting_policy: "MEMBERS_WITH_APPROVAL",
  visibility: "PUBLIC",
};

function options(labels: Record<string, string>) {
  return Object.entries(labels).map(([value, label]) => (
    <option key={value} value={value}>
      {label}
    </option>
  ));
}

interface CommunityFormProps {
  initial?: CommunityFields;
  submitLabel: string;
  /** Rejects with the API error when the server refuses the values. */
  onSubmit: (values: CommunityFields) => Promise<unknown>;
  onCancel?: () => void;
}

export function CommunityForm({ initial, submitLabel, onSubmit, onCancel }: CommunityFormProps) {
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    control,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: initial ?? DEFAULTS });
  const isPrivate = useWatch({ control, name: "visibility" }) === "PRIVATE";

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await onSubmit(values);
    } catch (error) {
      setFormError(applyApiError(error, setError, FIELDS));
    }
  });

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      {formError && <Notice kind="error">{formError}</Notice>}
      <TextField label="Name" error={errors.name?.message} {...register("name")} />
      <TextAreaField
        label="About"
        rows={5}
        error={errors.description?.message}
        {...register("description")}
      />
      <TextField
        label="Category"
        placeholder="Technology"
        error={errors.category?.message}
        {...register("category")}
      />
      <SelectField
        label="Who can see it"
        hint={
          isPrivate
            ? "A private community cannot be found or requested; people join by invitation."
            : undefined
        }
        {...register("visibility")}
      >
        {options(VISIBILITY_LABELS)}
      </SelectField>
      <SelectField label="How people join" {...register("join_policy")}>
        {options(JOIN_POLICY_LABELS)}
      </SelectField>
      <SelectField
        label="Who can share opportunities here"
        hint="Opportunities arrive in a later release; this setting is saved for then."
        {...register("posting_policy")}
      >
        {options(POSTING_POLICY_LABELS)}
      </SelectField>
      <div className="button-row">
        <button type="submit" className="primary" disabled={isSubmitting}>
          {isSubmitting ? "Saving…" : submitLabel}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} disabled={isSubmitting}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
