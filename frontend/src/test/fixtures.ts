import type { Me, Session } from "../features/auth/types";
import type { OpportunityDetail } from "../features/opportunities/types";

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

type OpportunityViewer = OpportunityDetail["viewer"];

/** What the viewer may do with an opportunity: by default, nothing but look. */
export function makeViewer(overrides: Partial<OpportunityViewer> = {}): OpportunityViewer {
  return {
    can_manage: false,
    editable_fields: [],
    is_saved: false,
    can_apply: false,
    application: null,
    ...overrides,
  };
}

export function makeSession(user: Me = makeMe(), accessToken = "access-1"): Session {
  return { access_token: accessToken, expires_in: 600, user };
}
