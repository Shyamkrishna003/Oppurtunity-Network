import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { SelectField, TextAreaField, TextField } from "../../components/Field";
import { Notice } from "../../components/Notice";
import { applyApiError } from "../../services/formErrors";
import type { OwnProfile } from "../auth/types";
import { useUpdateProfile } from "./api";
import { EXPERIENCE_LEVELS, WORK_MODES } from "./labels";

const schema = z.object({
  display_name: z.string().trim().min(1, "Enter your name.").max(80),
  headline: z.string().trim().max(140, "Use at most 140 characters."),
  bio: z.string().trim().max(2000, "Use at most 2000 characters."),
  city: z.string().trim().max(80),
  region: z.string().trim().max(80),
  country_code: z
    .string()
    .trim()
    .regex(/^([A-Za-z]{2})?$/, "Use a two-letter country code, such as IN."),
  work_mode_preference: z.enum(["", "REMOTE", "HYBRID", "ONSITE"]),
  experience_level: z.enum(["", "INTERN", "ENTRY", "MID", "SENIOR", "LEAD"]),
});
type Values = z.infer<typeof schema>;
const FIELDS = Object.keys(schema.shape) as (keyof Values)[];

export function BasicsForm({ profile }: { profile: OwnProfile }) {
  const update = useUpdateProfile();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isDirty },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: profile });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const me = await update.mutateAsync(values);
      reset(me.profile);
    } catch (error) {
      setFormError(applyApiError(error, setError, FIELDS));
    }
  });

  return (
    <form onSubmit={(event) => void onSubmit(event)} noValidate>
      {formError && <Notice kind="error">{formError}</Notice>}
      {update.isSuccess && !isDirty && <Notice kind="ok">Saved.</Notice>}
      <TextField label="Name" error={errors.display_name?.message} {...register("display_name")} />
      <TextField
        label="Headline"
        hint="One line about what you do, e.g. “Backend engineer, Django and PostgreSQL”."
        error={errors.headline?.message}
        {...register("headline")}
      />
      <TextAreaField label="About" rows={5} error={errors.bio?.message} {...register("bio")} />
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
      <div className="field-row">
        <SelectField label="Preferred work mode" {...register("work_mode_preference")}>
          <option value="">No preference</option>
          {Object.entries(WORK_MODES).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </SelectField>
        <SelectField label="Experience level" {...register("experience_level")}>
          <option value="">Not specified</option>
          {Object.entries(EXPERIENCE_LEVELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </SelectField>
      </div>
      <button type="submit" className="primary" disabled={update.isPending || !isDirty}>
        {update.isPending ? "Saving…" : "Save"}
      </button>
    </form>
  );
}
