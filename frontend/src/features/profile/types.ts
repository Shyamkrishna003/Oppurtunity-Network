import type { ExperienceLevel, SkillSets, WorkMode } from "../auth/types";

export interface Experience {
  id: string;
  title: string;
  organization_name: string;
  start_date: string;
  end_date: string | null;
  description: string;
}

export interface Education {
  id: string;
  institution: string;
  degree: string;
  field_of_study: string;
  start_date: string;
  end_date: string | null;
}

/** Another user's profile as the viewer may see it; hidden sections are null. */
export interface PublicProfile {
  id: string;
  is_self: boolean;
  display_name: string;
  headline: string;
  bio: string;
  avatar_url: string | null;
  country_code: string;
  region: string;
  city: string;
  work_mode_preference: WorkMode;
  experience_level: ExperienceLevel;
  skills: SkillSets;
  email: string | null;
  experiences: Experience[] | null;
  educations: Education[] | null;
}

export interface BlockedUser {
  id: string;
  display_name: string;
  avatar_url: string | null;
  blocked_at: string;
}

export interface Page<T> {
  results: T[];
  next: string | null;
  previous: string | null;
}
