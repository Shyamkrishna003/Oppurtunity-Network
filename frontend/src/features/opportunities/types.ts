import type { ApplicationStatus } from "../applications/types";
import type { ExperienceLevel, Skill, WorkMode } from "../auth/types";
import type { Person } from "../organizations/types";

export type OpportunityType = "JOB" | "EVENT";
export type OpportunityStatus = "DRAFT" | "PUBLISHED" | "CLOSED" | "EXPIRED" | "ARCHIVED";
export type OpportunityVisibility = "PUBLIC" | "COMMUNITY" | "ORGANIZATION";
export type CloseReason = "FILLED" | "CANCELLED" | "OTHER";
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

export const CLOSE_REASON_LABELS: Record<CloseReason, string> = {
  FILLED: "The position was filled",
  CANCELLED: "The opening was cancelled",
  OTHER: "Another reason",
};

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
  job: JobDetail;
}

export interface NewOpportunityInput extends OpportunityInput {
  type: OpportunityType;
  organization_id: string | null;
}

export interface Opportunity extends Omit<OpportunityInput, "skill_ids"> {
  id: string;
  type: OpportunityType;
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
  };
}
