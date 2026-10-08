export type ProfileVisibility = "PUBLIC" | "CONNECTIONS" | "COMMUNITY" | "PRIVATE";
export type WorkMode = "" | "REMOTE" | "HYBRID" | "ONSITE";
export type ExperienceLevel = "" | "INTERN" | "ENTRY" | "MID" | "SENIOR" | "LEAD";

export interface Skill {
  id: string;
  name: string;
  slug: string;
}

export interface SkillSets {
  has: Skill[];
  interested: Skill[];
}

export interface OwnProfile {
  display_name: string;
  headline: string;
  bio: string;
  avatar_url: string | null;
  country_code: string;
  region: string;
  city: string;
  work_mode_preference: WorkMode;
  experience_level: ExperienceLevel;
  visibility: ProfileVisibility;
  show_contact: boolean;
  show_history: boolean;
  accepts_referral_requests: boolean;
}

export interface Me {
  id: string;
  email: string;
  email_verified: boolean;
  platform_role: "USER" | "MODERATOR" | "ADMIN";
  created_at: string;
  profile: OwnProfile;
  skills: SkillSets;
}

export interface Session {
  access_token: string;
  expires_in: number;
  user: Me;
}
