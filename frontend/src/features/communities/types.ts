import type { Person } from "../organizations/types";

export type CommunityRole = "OWNER" | "ADMIN" | "MODERATOR" | "MEMBER";
export type MemberStatus =
  "PENDING" | "INVITED" | "ACTIVE" | "REJECTED" | "LEFT" | "REMOVED" | "BANNED";
/** The states a list of people can be requested for. */
export type ListableStatus = "ACTIVE" | "PENDING" | "INVITED" | "BANNED";
export type JoinPolicy = "OPEN" | "APPROVAL" | "INVITE_ONLY";
export type PostingPolicy = "ADMINS_ONLY" | "MEMBERS_WITH_APPROVAL" | "MEMBERS_AUTO";
export type CommunityVisibility = "PUBLIC" | "PRIVATE";
/** What pressing the join button would do for this viewer; null when they cannot join. */
export type JoinAction = "join" | "request" | "accept";

export const ROLE_LABELS: Record<CommunityRole, string> = {
  OWNER: "Owner",
  ADMIN: "Admin",
  MODERATOR: "Moderator",
  MEMBER: "Member",
};

/** Most to least privileged, for lists and menus. */
export const ROLE_ORDER: CommunityRole[] = ["OWNER", "ADMIN", "MODERATOR", "MEMBER"];

export const JOIN_POLICY_LABELS: Record<JoinPolicy, string> = {
  OPEN: "Anyone can join",
  APPROVAL: "Admins approve each request",
  INVITE_ONLY: "By invitation only",
};

export const POSTING_POLICY_LABELS: Record<PostingPolicy, string> = {
  ADMINS_ONLY: "Admins only",
  MEMBERS_WITH_APPROVAL: "Members, after review",
  MEMBERS_AUTO: "Members, without review",
};

export const VISIBILITY_LABELS: Record<CommunityVisibility, string> = {
  PUBLIC: "Public: anyone can find and view it",
  PRIVATE: "Private: only members and invited people can see it",
};

export interface CommunityFields {
  name: string;
  description: string;
  category: string;
  join_policy: JoinPolicy;
  posting_policy: PostingPolicy;
  visibility: CommunityVisibility;
}

export interface Community extends CommunityFields {
  id: string;
  slug: string;
  is_verified: boolean;
  status: "ACTIVE" | "SUSPENDED";
  member_count: number;
  created_at: string;
}

export interface Rule {
  title: string;
  body: string;
}

/** What the signed-in user is and may do here. The server enforces all of it. */
export interface CommunityViewer {
  membership_id: string | null;
  status: ListableStatus | null;
  role: CommunityRole | null;
  join_action: JoinAction | null;
  can_manage: boolean;
  can_review_requests: boolean;
  assignable_roles: CommunityRole[];
}

export interface CommunityDetail extends Community {
  rules: Rule[];
  viewer: CommunityViewer;
}

export interface MyCommunity {
  membership_id: string;
  community: { id: string; name: string; slug: string };
  role: CommunityRole;
  status: "ACTIVE" | "INVITED" | "PENDING";
}

export interface CommunityMember {
  id: string;
  user: Person;
  role: CommunityRole;
  status: MemberStatus;
  joined_at: string | null;
}

export type MemberAction = "approve" | "reject" | "remove" | "ban" | "unban";
