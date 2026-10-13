import type { OpportunityStatus } from "../opportunities/types";
import type { Person } from "../organizations/types";

export type ReferralStatus =
  | "REQUESTED"
  | "ACCEPTED"
  | "DECLINED"
  | "CANCELLED"
  | "EXPIRED"
  | "REFERRED"
  | "APPLICATION_SUBMITTED"
  | "INTERVIEW"
  | "OFFER"
  | "JOINED"
  | "CLOSED";

export const REFERRAL_STATUS_LABELS: Record<ReferralStatus, string> = {
  REQUESTED: "Requested",
  ACCEPTED: "Accepted",
  DECLINED: "Declined",
  CANCELLED: "Cancelled",
  EXPIRED: "Expired",
  REFERRED: "Referred",
  APPLICATION_SUBMITTED: "Application submitted",
  INTERVIEW: "Interview",
  OFFER: "Offer",
  JOINED: "Joined",
  CLOSED: "Closed",
};

/** Ended without a hire; everything else is still going, or ended well. */
const ENDED: ReadonlySet<ReferralStatus> = new Set(["DECLINED", "CANCELLED", "EXPIRED", "CLOSED"]);

export function referralBadgeClass(status: ReferralStatus): string {
  return ENDED.has(status) ? "badge" : "badge badge-ok";
}

/** What the viewer may do with a referral, as the server offers it. */
export type ReferralAction = "accept" | "decline" | "cancel" | "refer" | "back_out";

export interface Referral {
  id: string;
  status: ReferralStatus;
  created_at: string;
  status_changed_at: string;
  /** When an unanswered request lapses. */
  expires_at: string;
  opportunity: {
    id: string;
    title: string;
    status: OpportunityStatus;
    organization: { id: string; name: string } | null;
  };
  requester: Person;
  referrer: Person;
}

export interface ReferralStep {
  /** Empty for the first step: the request being made. */
  from_status: ReferralStatus | "";
  to_status: ReferralStatus;
  created_at: string;
}

export interface ReferralDetail extends Referral {
  /** From the requester to the referrer. Empty for the job's managers. */
  message: string;
  /** From the referrer to the people hiring. Empty for the requester. */
  endorsement_note: string;
  referred_at: string | null;
  /** The application the referral follows, for those who can open it. */
  application_id: string | null;
  history: ReferralStep[];
  viewer: {
    is_requester: boolean;
    is_referrer: boolean;
    actions: ReferralAction[];
  };
}

/** The viewer's own connections they could ask for one job. */
export interface EligibleReferrers {
  referrers: Person[];
  /** How many more requests the viewer may have open for this job. */
  remaining: number;
}

/** A referral attached to an application, as the people hiring see it. */
export interface ApplicationReferral {
  id: string;
  referrer: Person;
  endorsement_note: string;
  referred_at: string;
}

export const MESSAGE_MAX = 1000;
export const ENDORSEMENT_MIN = 20;
export const ENDORSEMENT_MAX = 2000;
