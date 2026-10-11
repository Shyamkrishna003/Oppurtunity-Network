import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { SelectField, TextAreaField, TextField } from "../../components/Field";
import { Notice } from "../../components/Notice";
import { ApiError } from "../../services/http";
import type { Skill } from "../auth/types";
import { EXPERIENCE_LEVELS, WORK_MODES } from "../profile/labels";
import { SkillPicker } from "../profile/SkillPicker";
import {
  EMPLOYMENT_TYPE_LABELS,
  SALARY_PERIOD_LABELS,
  VISIBILITY_LABELS,
  type Opportunity,
  type OpportunityInput,
  type OpportunityVisibility,
} from "./types";

const MAX_SKILLS = 15;
const wholeNumber = z
  .string()
  .trim()
  .regex(/^\d{0,9}$/, "Enter a whole number.");

const schema = z
  .object({
    title: z.string().trim().min(1, "Enter a title.").max(160),
    description: z.string().trim().max(10000, "Use at most 10,000 characters."),
    visibility: z.enum(["PUBLIC", "COMMUNITY", "ORGANIZATION"]),
    work_mode: z.enum(["", "REMOTE", "HYBRID", "ONSITE"]),
    city: z.string().trim().max(80),
    region: z.string().trim().max(80),
    country_code: z
      .string()
      .trim()
      .regex(/^([A-Za-z]{2})?$/, "Use a two-letter country code, such as IN."),
    deadline: z.string(),
    department: z.string().trim().max(80),
    employment_type: z.enum(["", "FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP", "TEMPORARY"]),
    experience_level: z.enum(["", "INTERN", "ENTRY", "MID", "SENIOR", "LEAD"]),
    salary_min: wholeNumber,
    salary_max: wholeNumber,
    salary_currency: z
      .string()
      .trim()
      .regex(/^([A-Za-z]{3})?$/, "Use a three-letter currency code, such as INR."),
    salary_period: z.enum(["", "YEAR", "MONTH", "HOUR"]),
    application_method: z.enum(["INTERNAL", "EXTERNAL"]),
    external_url: z.string().trim().max(200),
    openings: z
      .string()
      .trim()
      .regex(/^[1-9]\d{0,3}$/, "Enter a number from 1 upwards."),
  })
  .refine((v) => !v.salary_min || !v.salary_max || Number(v.salary_min) <= Number(v.salary_max), {
    path: ["salary_max"],
    message: "The maximum must not be below the minimum.",
  })
  .refine(
    (v) => v.application_method === "INTERNAL" || /^https?:\/\/\S+\.\S+/.test(v.external_url),
    {
      path: ["external_url"],
      message: "Enter the full address where people apply, starting with http:// or https://.",
    },
  );
type Values = z.infer<typeof schema>;
type FieldName = keyof Values;

const EMPTY: Values = {
  title: "",
  description: "",
  visibility: "PUBLIC",
  work_mode: "",
  city: "",
  region: "",
  country_code: "",
  deadline: "",
  department: "",
  employment_type: "",
  experience_level: "",
  salary_min: "",
  salary_max: "",
  salary_currency: "",
  salary_period: "",
  application_method: "INTERNAL",
  external_url: "",
  openings: "1",
};

/** The local calendar date of a timestamp, as a date input wants it. */
function toDateInput(iso: string | null): string {
  if (!iso) {
    return "";
  }
  const date = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function fromOpportunity(opportunity: Opportunity): Values {
  const { job } = opportunity;
  return {
    title: opportunity.title,
    description: opportunity.description,
    visibility: opportunity.visibility,
    work_mode: opportunity.work_mode,
    city: opportunity.city,
    region: opportunity.region,
    country_code: opportunity.country_code,
    deadline: toDateInput(opportunity.deadline),
    department: job.department,
    employment_type: job.employment_type,
    experience_level: job.experience_level,
    salary_min: job.salary_min?.toString() ?? "",
    salary_max: job.salary_max?.toString() ?? "",
    salary_currency: job.salary_currency,
    salary_period: job.salary_period,
    application_method: job.application_method,
    external_url: job.external_url,
    openings: String(job.openings),
  };
}

function toInput(values: Values, skills: Skill[]): OpportunityInput {
  const number = (text: string) => (text === "" ? null : Number(text));
  return {
    title: values.title,
    description: values.description,
    visibility: values.visibility,
    work_mode: values.work_mode,
    city: values.city,
    region: values.region,
    country_code: values.country_code,
    // The deadline is the end of the chosen day, in the poster's own time zone.
    deadline: values.deadline ? new Date(`${values.deadline}T23:59:59`).toISOString() : null,
    skill_ids: skills.map((skill) => skill.id),
    job: {
      department: values.department,
      employment_type: values.employment_type,
      experience_level: values.experience_level,
      salary_min: number(values.salary_min),
      salary_max: number(values.salary_max),
      salary_currency: values.salary_currency,
      salary_period: values.salary_period,
      application_method: values.application_method,
      external_url: values.application_method === "EXTERNAL" ? values.external_url : "",
      openings: Number(values.openings),
    },
  };
}

function options(labels: Record<string, string>) {
  return Object.entries(labels).map(([value, label]) => (
    <option key={value} value={value}>
      {label}
    </option>
  ));
}

interface JobFormProps {
  /** The opportunity being edited; omit when creating. */
  opportunity?: Opportunity;
  /** Whether "members of the organization" can be offered as an audience. */
  hasOrganization: boolean;
  /** Field names that may still change; null means all. Others are shown disabled. */
  editableFields: string[] | null;
  canCreateSkills: boolean;
  submitLabel: string;
  /** Rejects with the API error when the server refuses the values. */
  onSubmit: (input: Partial<OpportunityInput>) => Promise<unknown>;
  onCancel?: () => void;
}

export function JobForm({
  opportunity,
  hasOrganization,
  editableFields,
  canCreateSkills,
  submitLabel,
  onSubmit,
  onCancel,
}: JobFormProps) {
  const [formError, setFormError] = useState<string | null>(null);
  const [skillError, setSkillError] = useState<string | null>(null);
  const [skills, setSkills] = useState<Skill[]>(opportunity?.skills ?? []);
  const {
    register,
    handleSubmit,
    setError,
    control,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: opportunity ? fromOpportunity(opportunity) : EMPTY,
  });
  const isExternal = useWatch({ control, name: "application_method" }) === "EXTERNAL";

  // After publishing only a few fields stay open. The number of openings is the one
  // job-specific field among them.
  const restricted = editableFields !== null;
  const open = new Set([...(editableFields ?? []), "openings"]);
  const locked = (field: FieldName) => restricted && !open.has(field);
  const field = (name: FieldName) => ({
    error: errors[name]?.message,
    disabled: locked(name),
    ...register(name),
  });

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    setSkillError(null);
    const input = toInput(values, skills);
    const body: Partial<OpportunityInput> = restricted
      ? { description: input.description, deadline: input.deadline, job: input.job }
      : input;
    try {
      await onSubmit(body);
    } catch (error) {
      if (!(error instanceof ApiError)) {
        setFormError("Something went wrong. Try again.");
        return;
      }
      // Server field names are nested ("job.salary_max"); the form's are flat.
      let matched = false;
      for (const [key, messages] of Object.entries(error.fieldErrors)) {
        const name = key.replace(/^job\./, "");
        if (key === "skill_ids") {
          setSkillError(messages.join(" "));
          matched = true;
        } else if (name in EMPTY) {
          setError(name as FieldName, { type: "server", message: messages.join(" ") });
          matched = true;
        }
      }
      setFormError(matched ? "Check the highlighted details." : error.message);
    }
  });

  const audiences = Object.fromEntries(
    Object.entries(VISIBILITY_LABELS).filter(
      ([value]) => hasOrganization || (value as OpportunityVisibility) !== "ORGANIZATION",
    ),
  );

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      {formError && <Notice kind="error">{formError}</Notice>}
      {restricted && (
        <Notice kind="ok">
          This job is published. You can still change the description, the deadline and the number
          of openings; everything else is fixed so it stays the job people saw.
        </Notice>
      )}

      <TextField label="Job title" {...field("title")} />
      <TextAreaField label="Description" rows={8} {...field("description")} />

      <div className="field-row">
        <SelectField label="Employment type" {...field("employment_type")}>
          <option value="">Choose…</option>
          {options(EMPLOYMENT_TYPE_LABELS)}
        </SelectField>
        <SelectField label="Experience level" {...field("experience_level")}>
          <option value="">Choose…</option>
          {options(EXPERIENCE_LEVELS)}
        </SelectField>
        <TextField label="Department (optional)" {...field("department")} />
      </div>

      <div className="field-row">
        <SelectField label="Work mode" {...field("work_mode")}>
          <option value="">Choose…</option>
          {options(WORK_MODES)}
        </SelectField>
        <TextField label="City" {...field("city")} />
        <TextField label="State or region" {...field("region")} />
        <TextField label="Country code" maxLength={2} placeholder="IN" {...field("country_code")} />
      </div>

      <fieldset disabled={restricted} className="plain-fieldset">
        <SkillPicker
          label="Skills needed"
          value={skills}
          onChange={setSkills}
          max={MAX_SKILLS}
          canCreate={canCreateSkills}
        />
        {skillError && (
          <p className="field-error" role="alert">
            {skillError}
          </p>
        )}
      </fieldset>

      <div className="field-row">
        <TextField label="Salary from (optional)" inputMode="numeric" {...field("salary_min")} />
        <TextField label="Salary to (optional)" inputMode="numeric" {...field("salary_max")} />
        <TextField label="Currency" maxLength={3} placeholder="INR" {...field("salary_currency")} />
        <SelectField label="Salary is" {...field("salary_period")}>
          <option value="">Choose…</option>
          {options(SALARY_PERIOD_LABELS)}
        </SelectField>
      </div>

      <div className="field-row">
        <TextField label="Number of openings" inputMode="numeric" {...field("openings")} />
        <TextField
          label="Apply by (optional)"
          type="date"
          hint="Applications close at the end of this day."
          {...field("deadline")}
        />
      </div>

      <SelectField label="How people apply" {...field("application_method")}>
        <option value="INTERNAL">On Opportunity Network</option>
        <option value="EXTERNAL">On another website</option>
      </SelectField>
      {isExternal && (
        <TextField
          label="Address of the application page"
          type="url"
          placeholder="https://example.com/careers/backend-engineer"
          {...field("external_url")}
        />
      )}

      <SelectField label="Who can see it" {...field("visibility")}>
        {options(audiences)}
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
