import type { Me, Session } from "../features/auth/types";

export function makeMe(overrides: Partial<Me> = {}): Me {
  return {
    id: "0199b7c0-0000-7000-8000-000000000001",
    email: "ada@example.com",
    email_verified: true,
    platform_role: "USER",
    created_at: "2026-10-01T00:00:00Z",
    profile: {
      display_name: "Ada Lovelace",
      headline: "",
      bio: "",
      avatar_url: null,
      country_code: "",
      region: "",
      city: "",
      work_mode_preference: "",
      experience_level: "",
      visibility: "PUBLIC",
      show_contact: false,
      show_history: true,
      accepts_referral_requests: true,
    },
    skills: { has: [], interested: [] },
    ...overrides,
  };
}

export function makeSession(user: Me = makeMe(), accessToken = "access-1"): Session {
  return { access_token: accessToken, expires_in: 600, user };
}
