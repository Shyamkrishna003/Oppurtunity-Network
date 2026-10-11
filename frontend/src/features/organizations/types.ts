export type OrganizationRole = "OWNER" | "ADMIN" | "RECRUITER" | "MEMBER";
export type InvitationStatus = "PENDING" | "ACCEPTED" | "DECLINED" | "REVOKED" | "EXPIRED";

export const ROLE_LABELS: Record<OrganizationRole, string> = {
  OWNER: "Owner",
  ADMIN: "Admin",
  RECRUITER: "Recruiter",
  MEMBER: "Member",
};

/** Most to least privileged, for lists and menus. */
export const ROLE_ORDER: OrganizationRole[] = ["OWNER", "ADMIN", "RECRUITER", "MEMBER"];

export interface OrganizationFields {
  name: string;
  description: string;
  website: string;
  industry: string;
  country_code: string;
  region: string;
  city: string;
}

export interface Organization extends OrganizationFields {
  id: string;
  slug: string;
  verification_status: "UNVERIFIED" | "PENDING" | "VERIFIED" | "REJECTED";
  status: "ACTIVE" | "SUSPENDED";
  member_count: number;
  created_at: string;
}

/** What the signed-in user is and may do here. The server enforces all of it. */
export interface OrganizationViewer {
  membership_id: string | null;
  role: OrganizationRole | null;
  is_public: boolean | null;
  can_manage: boolean;
  assignable_roles: OrganizationRole[];
}

export interface OrganizationDetail extends Organization {
  viewer: OrganizationViewer;
}

export interface OrganizationRef {
  id: string;
  name: string;
  slug: string;
}

export interface MyOrganization {
  membership_id: string;
  organization: OrganizationRef;
  role: OrganizationRole;
}

export interface Person {
  id: string;
  display_name: string;
  headline: string;
  avatar_url: string | null;
}

export interface Member {
  id: string;
  user: Person;
  role: OrganizationRole;
  is_public: boolean;
  joined_at: string;
}

export interface Invitation {
  id: string;
  email: string;
  role: OrganizationRole;
  status: InvitationStatus;
  expires_at: string;
  invited_by: string | null;
  created_at: string;
}

export interface ReceivedInvitation {
  organization: OrganizationRef;
  role: OrganizationRole;
  status: InvitationStatus;
  expires_at: string;
  invited_by: string | null;
}
