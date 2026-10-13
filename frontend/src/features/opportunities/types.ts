import type { ApplicationStatus } from "../applications/types";
import type { ExperienceLevel, Skill, WorkMode } from "../auth/types";
import type { Person } from "../organizations/types";

export type OpportunityType = "JOB" | "EVENT";
export type OpportunityStatus = "DRAFT" | "PUBLISHED" | "CLOSED" | "EXPIRED" | "ARCHIVED";
export type OpportunityVisibility = "PUBLIC" | "COMMUNITY" | "ORGANIZATION";
/** `COMPLETED` is only ever set by the server, when an event has taken place. */
export type CloseReason = "FILLED" | "CANCELLED" | "COMPLETED" | "OTHER";
export type EventStatus =
  "SCHEDULED" | "REGISTRATION_OPEN" | "REGISTRATION_CLOSED" | "COMPLETED" | "CANCELLED";
export type EventFormat = "IN_PERSON" | "ONLINE" | "HYBRID";
export type AttendeeVisibility = "PUBLIC" | "ATTENDEES" | "HIDDEN";
export type EmploymentType = "FULL_TIME" | "PART_TIME" | "CONTRACT" | "INTERNSHIP" | "TEMPORARY";
export type SalaryPeriod = "YEAR" | "MONTH" | "HOUR";
export type ApplicationMethod = "INTERNAL" | "EXTERNAL";

export const STATUS_LABELS: Record<OpportunityStatus, string> = {
  DRAFT: "Draft",
  PUBLISHED: "Published",
  CLOSED: "Closed",
  EXPIRED: "Expired",
  ARCHIVED: "Archived",
};

export const VISIBILITY_LABELS: Record<OpportunityVisibility, string> = {
  PUBLIC: "Everyone",
  COMMUNITY: "Only members of the communities it is shared with",
  ORGANIZATION: "Only members of the organization",
};

export const EMPLOYMENT_TYPE_LABELS: Record<EmploymentType, string> = {
  FULL_TIME: "Full-time",
  PART_TIME: "Part-time",
  CONTRACT: "Contract",
  INTERNSHIP: "Internship",
  TEMPORARY: "Temporary",
};

export const SALARY_PERIOD_LABELS: Record<SalaryPeriod, string> = {
  YEAR: "per year",
  MONTH: "per month",
  HOUR: "per hour",
};

/** The reasons a person can choose when closing a job. */
export const CLOSE_REASON_LABELS: Record<Exclude<CloseReason, "COMPLETED">, string> = {
  FILLED: "The position was filled",
  CANCELLED: "The opening was cancelled",
  OTHER: "Another reason",
};

export const TYPE_LABELS: Record<OpportunityType, string> = { JOB: "Job", EVENT: "Event" };

export const EVENT_FORMAT_LABELS: Record<EventFormat, string> = {
  IN_PERSON: "In person",
  ONLINE: "Online",
  HYBRID: "In person and online",
};

export const EVENT_STATUS_LABELS: Record<EventStatus, string> = {
  SCHEDULED: "Registration opens soon",
  REGISTRATION_OPEN: "Registration open",
  REGISTRATION_CLOSED: "Registration closed",
  COMPLETED: "This event has taken place",
  CANCELLED: "Cancelled",
};

export const ATTENDEE_VISIBILITY_LABELS: Record<AttendeeVisibility, string> = {
  PUBLIC: "Anyone who can see the event",
  ATTENDEES: "People who are going",
  HIDDEN: "Only the organizers",
};

/** The fields of an event that its organizer edits. */
export interface EventInput {
  format: EventFormat | "";
  start_at: string | null;
  end_at: string | null;
  /** An IANA name such as "Asia/Kolkata": the place the times are meant in. */
  timezone: string;
  venue: string;
  online_url: string;
  /** Null means there is no limit. */
  capacity: number | null;
  /** Null means registration opens as soon as the event is published. */
  registration_opens_at: string | null;
  attendee_visibility: AttendeeVisibility;
}

export interface EventDetail extends EventInput {
  /** Empty until the event is published. */
  event_status: EventStatus | "";
  confirmed_count: number;
  /** `online_url` itself is only sent to the people who run the event. */
  has_online_url: boolean;
}

export interface JobDetail {
  department: string;
  employment_type: EmploymentType | "";
  experience_level: ExperienceLevel;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  salary_period: SalaryPeriod | "";
  application_method: ApplicationMethod;
  external_url: string;
  openings: number;
}

/** The fields a manager edits, as the API accepts them. */
export interface OpportunityInput {
  title: string;
  description: string;
  visibility: OpportunityVisibility;
  work_mode: WorkMode;
  country_code: string;
  region: string;
  city: string;
  deadline: string | null;
  skill_ids: string[];
  /** Whichever matches the opportunity's type; the other is left out. */
  job?: JobDetail;
  event?: EventInput;
}

export interface NewOpportunityInput extends OpportunityInput {
  type: OpportunityType;
  organization_id: string | null;
}

export interface Opportunity extends Omit<OpportunityInput, "skill_ids" | "job" | "event"> {
  id: string;
  type: OpportunityType;
  /** Exactly one of these is set, according to `type`. */
  job: JobDetail | null;
  event: EventDetail | null;
  status: OpportunityStatus;
  published_at: string | null;
  closed_at: string | null;
  close_reason: CloseReason | "";
  created_at: string;
  organization: {
    id: string;
    name: string;
    slug: string;
    verification_status: "UNVERIFIED" | "PENDING" | "VERIFIED" | "REJECTED";
  } | null;
  /** The person behind a personal opportunity; null when an organization posted it. */
  posted_by: Person | null;
  skills: Skill[];
}

export type MatchKind = "skill" | "interest" | "community" | "location" | "work_mode";

/** Why an opportunity fits the signed-in user: a fixed sum over what they told us. */
export interface Match {
  score: number;
  reasons: { kind: MatchKind; label: string }[];
}

/** An opportunity in the feed. `match` is null for visitors. */
export interface FeedItem extends Opportunity {
  is_saved: boolean;
  match: Match | null;
}

export interface SavedItem {
  saved_at: string;
  opportunity: Opportunity;
}

export type FeedSort = "newest" | "deadline" | "relevant";

export const SORT_LABELS: Record<FeedSort, string> = {
  relevant: "Best match",
  newest: "Newest",
  deadline: "Closing soonest",
};

export type ShareStatus = "PENDING" | "APPROVED" | "REJECTED" | "REMOVED";

export const SHARE_STATUS_LABELS: Record<ShareStatus, string> = {
  PENDING: "Waiting for review",
  APPROVED: "Shown",
  REJECTED: "Rejected",
  REMOVED: "Removed by the community",
};

export interface CommunityRef {
  id: string;
  name: string;
  slug: string;
}

/** One community an opportunity was offered to, as its managers see it. */
export interface Share {
  id: string;
  community: CommunityRef;
  status: ShareStatus;
  rejection_reason: string;
  is_featured: boolean;
  created_at: string;
}

/** One of the manager's communities and what sharing into it would do. */
export interface ShareOption {
  community: CommunityRef;
  /** The existing share's status, if the opportunity is already there. */
  current: ShareStatus | null;
  /** APPROVED: shown at once. PENDING: goes to review. null: not allowed. */
  outcome: ShareStatus | null;
}

/** An opportunity in a community's list. */
export interface CommunityOpportunity {
  share_id: string;
  is_featured: boolean;
  opportunity: Opportunity;
}

/** A share as the community's moderators see it. */
export interface Submission {
  id: string;
  status: ShareStatus;
  is_featured: boolean;
  rejection_reason: string;
  created_at: string;
  reviewed_at: string | null;
  submitted_by: Person | null;
  opportunity: Opportunity;
}

export type SubmissionAction = "approve" | "reject" | "remove" | "feature" | "unfeature";

export interface OpportunityDetail extends Opportunity {
  moderation_status: "VISIBLE" | "HIDDEN" | "REMOVED";
  /** Communities showing this opportunity, among those the viewer may see. */
  communities: CommunityRef[];
  viewer: {
    can_manage: boolean;
    /** Fields that may still be edited: null means all of them, an empty list none. */
    editable_fields: string[] | null;
    is_saved: boolean;
    /** Whether the viewer may apply now. False once they have, and for anyone signed out. */
    can_apply: boolean;
    /** The viewer's own application to this job, if they ever made one. */
    application: { id: string; status: ApplicationStatus } | null;
    /** Whether a referral can be asked for here. Says nothing about knowing anyone there. */
    can_request_referral: boolean;
  };
}
