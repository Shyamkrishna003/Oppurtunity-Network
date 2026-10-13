import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { SelectField, TextAreaField, TextField } from "../../components/Field";
import { Notice } from "../../components/Notice";
import { ApiError } from "../../services/http";
import type { Skill } from "../auth/types";
import {
  ATTENDEE_VISIBILITY_LABELS,
  EVENT_FORMAT_LABELS,
  VISIBILITY_LABELS,
  type Opportunity,
  type OpportunityInput,
  type OpportunityVisibility,
} from "../opportunities/types";
import { SkillPicker } from "../profile/SkillPicker";
import { browserTimeZone, timeZones, utcToZoned, zonedToUtc } from "./time";

const MAX_SKILLS = 15;
const dateTime = z.string().regex(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}.*)?$/, "Enter a date and time.");

const schema = z
  .object({
    title: z.string().trim().min(1, "Enter a title.").max(160),
    description: z.string().trim().max(10000, "Use at most 10,000 characters."),
    visibility: z.enum(["PUBLIC", "COMMUNITY", "ORGANIZATION"]),
    format: z.enum(["", "IN_PERSON", "ONLINE", "HYBRID"]),
    start_at: dateTime,
    end_at: dateTime,
    timezone: z.string().min(1, "Choose a time zone."),
    venue: z.string().trim().max(200),
    city: z.string().trim().max(80),
    region: z.string().trim().max(80),
    country_code: z
      .string()
      .trim()
      .regex(/^([A-Za-z]{2})?$/, "Use a two-letter country code, such as IN."),
    online_url: z
      .string()
      .trim()
      .max(200)
      .regex(/^(https?:\/\/\S+\.\S+)?$/, "Enter the full address, starting with https://."),
    capacity: z
      .string()
      .trim()
      .regex(/^([1-9]\d{0,5})?$/, "Enter a number from 1 upwards, or leave it empty."),
    deadline: dateTime,
    registration_opens_at: dateTime,
    attendee_visibility: z.enum(["PUBLIC", "ATTENDEES", "HIDDEN"]),
  })
  .refine((v) => !v.start_at || !v.end_at || v.end_at > v.start_at, {
    path: ["end_at"],
    message: "The event must end after it starts.",
  })
  .refine((v) => !v.deadline || !v.start_at || v.deadline <= v.start_at, {
    path: ["deadline"],
    message: "Registration must close before the event starts.",
  });
type Values = z.infer<typeof schema>;
type FieldName = keyof Values;

const EMPTY: Values = {
  title: "",
  description: "",
  visibility: "PUBLIC",
  format: "",
  start_at: "",
  end_at: "",
  timezone: "",
  venue: "",
  city: "",
  region: "",
  country_code: "",
  online_url: "",
  capacity: "",
  deadline: "",
  registration_opens_at: "",
  attendee_visibility: "ATTENDEES",
};

/** What stays open after publishing, beyond what every opportunity allows. */
const OPEN_WHEN_PUBLISHED: FieldName[] = ["venue", "online_url", "attendee_visibility", "capacity"];

function fromOpportunity(opportunity: Opportunity): Values {
  const { event } = opportunity;
  if (!event) {
    return EMPTY;
  }
  const zone = event.timezone || browserTimeZone();
  return {
    title: opportunity.title,
    description: opportunity.description,
    visibility: opportunity.visibility,
    format: event.format,
    start_at: utcToZoned(event.start_at, zone),
    end_at: utcToZoned(event.end_at, zone),
    timezone: zone,
    venue: event.venue,
    city: opportunity.city,
    region: opportunity.region,
    country_code: opportunity.country_code,
    online_url: event.online_url,
    capacity: event.capacity?.toString() ?? "",
    deadline: utcToZoned(opportunity.deadline, zone),
    registration_opens_at: utcToZoned(event.registration_opens_at, zone),
    attendee_visibility: event.attendee_visibility,
  };
}

function toInput(values: Values, skills: Skill[]): OpportunityInput {
  const online = values.format === "ONLINE";
  const instant = (local: string) => zonedToUtc(local, values.timezone);
  return {
    title: values.title,
    description: values.description,
    visibility: values.visibility,
    // Not chosen for an event: the server sets it from the format.
    work_mode: "",
    city: online ? "" : values.city,
    region: online ? "" : values.region,
    country_code: online ? "" : values.country_code,
    deadline: instant(values.deadline),
    skill_ids: skills.map((skill) => skill.id),
    event: {
      format: values.format,
      start_at: instant(values.start_at),
      end_at: instant(values.end_at),
      timezone: values.timezone,
      venue: online ? "" : values.venue,
      online_url: values.format === "IN_PERSON" ? "" : values.online_url,
      capacity: values.capacity === "" ? null : Number(values.capacity),
      registration_opens_at: instant(values.registration_opens_at),
      attendee_visibility: values.attendee_visibility,
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

interface EventFormProps {
  /** The event being edited; omit when creating. */
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

export function EventForm({
  opportunity,
  hasOrganization,
  editableFields,
  canCreateSkills,
  submitLabel,
  onSubmit,
  onCancel,
}: EventFormProps) {
  const [formError, setFormError] = useState<string | null>(null);
  const [skillError, setSkillError] = useState<string | null>(null);
  const [skills, setSkills] = useState<Skill[]>(opportunity?.skills ?? []);
  const zones = useMemo(() => timeZones(), []);
  const {
    register,
    handleSubmit,
    setError,
    control,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: opportunity
      ? fromOpportunity(opportunity)
      : { ...EMPTY, timezone: browserTimeZone() },
  });
  const format = useWatch({ control, name: "format" });
  const zone = useWatch({ control, name: "timezone" });

  const restricted = editableFields !== null;
  const open = new Set<string>([...(editableFields ?? []), ...OPEN_WHEN_PUBLISHED]);
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
    const body: Partial<OpportunityInput> =
      restricted && input.event
        ? {
            description: input.description,
            deadline: input.deadline,
            event: {
              // Sent back as they are, so the server sees nothing locked being changed.
              ...input.event,
              start_at: opportunity?.event?.start_at ?? input.event.start_at,
              end_at: opportunity?.event?.end_at ?? input.event.end_at,
              registration_opens_at:
                opportunity?.event?.registration_opens_at ?? input.event.registration_opens_at,
            },
          }
        : input;
    try {
      await onSubmit(body);
    } catch (error) {
      if (!(error instanceof ApiError)) {
        setFormError("Something went wrong. Try again.");
        return;
      }
      // Server field names are nested ("event.start_at"); the form's are flat.
      let matched = false;
      for (const [key, messages] of Object.entries(error.fieldErrors)) {
        const name = key.replace(/^event\./, "");
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
  const inZone = zone ? `Clock time in ${zone}.` : undefined;

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      {formError && <Notice kind="error">{formError}</Notice>}
      {restricted && (
        <Notice kind="ok">
          This event is published. You can still change the description, when registration closes,
          the venue, the joining link, the number of places and who sees the attendee list;
          everything else is fixed so it stays the event people saw.
        </Notice>
      )}

      <TextField label="Event name" {...field("title")} />
      <TextAreaField label="Description" rows={8} {...field("description")} />

      <div className="field-row">
        <SelectField label="Format" {...field("format")}>
          <option value="">Choose…</option>
          {options(EVENT_FORMAT_LABELS)}
        </SelectField>
        <SelectField label="Time zone" {...field("timezone")}>
          {zones.map((name) => (
            <option key={name} value={name}>
              {name.replaceAll("_", " ")}
            </option>
          ))}
        </SelectField>
      </div>

      <div className="field-row">
        <TextField label="Starts" type="datetime-local" hint={inZone} {...field("start_at")} />
        <TextField label="Ends" type="datetime-local" {...field("end_at")} />
      </div>

      {format !== "ONLINE" && (
        <>
          <TextField label="Venue" placeholder="Building, street or landmark" {...field("venue")} />
          <div className="field-row">
            <TextField label="City" {...field("city")} />
            <TextField label="State or region" {...field("region")} />
            <TextField
              label="Country code"
              maxLength={2}
              placeholder="IN"
              {...field("country_code")}
            />
          </div>
        </>
      )}
      {format !== "IN_PERSON" && (
        <TextField
          label="Link to join online (optional)"
          type="url"
          placeholder="https://meet.example.com/your-event"
          hint="Only you and the others running the event can see this for now."
          {...field("online_url")}
        />
      )}

      <div className="field-row">
        <TextField
          label="Places (optional)"
          inputMode="numeric"
          hint="Leave empty for no limit."
          {...field("capacity")}
        />
        <TextField
          label="Registration opens (optional)"
          type="datetime-local"
          hint="Leave empty to open when you publish."
          {...field("registration_opens_at")}
        />
        <TextField
          label="Registration closes (optional)"
          type="datetime-local"
          hint="Leave empty to close when the event starts."
          {...field("deadline")}
        />
      </div>

      <fieldset disabled={restricted} className="plain-fieldset">
        <SkillPicker
          label="Topics (optional)"
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
        <SelectField label="Who can see it" {...field("visibility")}>
          {options(audiences)}
        </SelectField>
        <SelectField label="Who can see who is going" {...field("attendee_visibility")}>
          {options(ATTENDEE_VISIBILITY_LABELS)}
        </SelectField>
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
