import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { TextAreaField, TextField } from "../../components/Field";
import { Notice } from "../../components/Notice";
import { applyApiError } from "../../services/formErrors";
import type { OrganizationFields } from "./types";

const schema = z.object({
  name: z.string().trim().min(1, "Enter the organization's name.").max(120),
  description: z.string().trim().max(4000, "Use at most 4000 characters."),
  website: z
    .string()
    .trim()
    .max(200)
    .refine((value) => value === "" || /^https?:\/\/\S+\.\S+/.test(value), {
      message: "Enter a full address starting with http:// or https://.",
    }),
  industry: z.string().trim().max(80),
  city: z.string().trim().max(80),
  region: z.string().trim().max(80),
  country_code: z
    .string()
    .trim()
    .regex(/^([A-Za-z]{2})?$/, "Use a two-letter country code, such as IN."),
});
type Values = z.infer<typeof schema>;
const FIELDS = Object.keys(schema.shape) as (keyof Values)[];

const EMPTY: Values = {
  name: "",
  description: "",
  website: "",
  industry: "",
  city: "",
  region: "",
  country_code: "",
};

interface OrganizationFormProps {
  initial?: OrganizationFields;
  submitLabel: string;
  /** Rejects with the API error when the server refuses the values. */
  onSubmit: (values: OrganizationFields) => Promise<unknown>;
  onCancel?: () => void;
}

export function OrganizationForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: OrganizationFormProps) {
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: initial ?? EMPTY });

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
      <div className="field-row">
        <TextField
          label="Website"
          type="url"
          placeholder="https://example.com"
          error={errors.website?.message}
          {...register("website")}
        />
        <TextField label="Industry" error={errors.industry?.message} {...register("industry")} />
      </div>
      <div className="field-row">
        <TextField label="City" error={errors.city?.message} {...register("city")} />
        <TextField label="State or region" error={errors.region?.message} {...register("region")} />
        <TextField
          label="Country code"
          maxLength={2}
          placeholder="IN"
          error={errors.country_code?.message}
          {...register("country_code")}
        />
      </div>
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
