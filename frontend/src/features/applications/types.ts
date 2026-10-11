import type { OpportunityStatus } from "../opportunities/types";
import type { Person } from "../organizations/types";

export type ApplicationStatus =
  | "APPLIED"
  | "SCREENING"
  | "SHORTLISTED"
  | "INTERVIEW"
  | "OFFER"
  | "HIRED"
  | "REJECTED"
  | "WITHDRAWN";

export const APPLICATION_STATUS_LABELS: Record<ApplicationStatus, string> = {
  APPLIED: "Applied",
  SCREENING: "Screening",
  SHORTLISTED: "Shortlisted",
  INTERVIEW: "Interview",
  OFFER: "Offer",
  HIRED: "Hired",
  REJECTED: "Not selected",
  WITHDRAWN: "Withdrawn",
};

/** Still being considered; the other three are final. */
const OPEN: ReadonlySet<ApplicationStatus> = new Set([
  "APPLIED",
  "SCREENING",
  "SHORTLISTED",
  "INTERVIEW",
  "OFFER",
]);

export function statusBadgeClass(status: ApplicationStatus): string {
  if (status === "HIRED" || OPEN.has(status)) {
    return "badge badge-ok";
  }
  return "badge";
}

export interface Application {
  id: string;
  status: ApplicationStatus;
  created_at: string;
  status_changed_at: string;
  opportunity: {
    id: string;
    title: string;
    status: OpportunityStatus;
    organization: { id: string; name: string } | null;
  };
}

export interface ApplicationStep {
  /** Empty for the first step: the application being made. */
  from_status: ApplicationStatus | "";
  to_status: ApplicationStatus;
  created_at: string;
}

export interface ApplicationDetail extends Application {
  cover_note: string;
  /** The applicant's headline as it was when they applied. */
  headline: string;
  applicant: Person;
  history: ApplicationStep[];
  viewer: {
    is_applicant: boolean;
    can_manage: boolean;
    can_withdraw: boolean;
    can_download_resume: boolean;
  };
}

export const RESUME_MAX_BYTES = 5 * 1024 * 1024;
export const COVER_NOTE_MAX = 4000;
