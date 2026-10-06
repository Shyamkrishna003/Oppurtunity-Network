# Opportunity Network — Implementation Plan (Planning Phase)

## Context

The repository contains only `CLAUDE.md` (engineering rules) and `PRD.md` (product requirements). There is no code, no git history, no tooling. This document is the pre-implementation architecture and roadmap: it reviews the PRD critically, fixes the domain model, state machines, authorization, API, real-time, async, search and frontend designs, cuts the MVP, and ends with the exact first task. Nothing is implemented until this is approved.

**Decisions that change the PRD and need your sign-off** (details in §2):

| # | Decision | Recommendation |
|---|---|---|
| D1 | MVP opportunity types | **Job + Event only.** Project and Mentorship move to the first post-MVP release. |
| D2 | "Referral" as an opportunity type | **Not a type.** A referral is a workflow (`ReferralRequest`) attached to an organization-owned Job. |
| D3 | Event lifecycle vs Opportunity lifecycle | Two fields, not one: `Opportunity.status` (publication) + `EventDetail.event_status` (registration/outcome). |
| D4 | WebSocket routes | **One user-scoped socket** `/ws/stream/` instead of `/ws/notifications/` + `/ws/conversations/{id}/`. Messages are sent over REST. |
| D5 | Auth mechanism | Short-lived access JWT in memory + rotating refresh token in an httpOnly cookie; single-use ticket for WebSocket. |
| D6 | `BLOCKED` connection state | Removed from `Connection`; blocks become a separate directional `UserBlock` table. |
| D7 | Subscriptions, discussions/resources, project workspace | Not built. No `subscriptions` app or table is created. |
| D8 | API prefix | `/api/v1/…` rather than `/api/…`. |
| D9 | Phase order | Notifications/WebSocket infrastructure moves before Applications; audit logging exists from Phase 0. |

---

## 1. Product Understanding

Opportunity Network is a multi-tenant platform whose unit of value is an **Opportunity** that moves through `Create → Publish → Distribute → Discover → Engage → Act → Track Outcome`. Three kinds of actors interact with it:

- **Individuals** discover, save, apply, register, and request referrals.
- **Organizations** (tenants) own opportunities and run pipelines on them.
- **Communities** (tenants) are distribution channels with their own moderation gate.

What makes it more than a job board: (a) one opportunity is distributed to several communities, each approving it independently; (b) referrals are an explicit, consented, tracked workflow; (c) success is measured in outcomes (hires, attendance), not engagement. Discovery is deterministic and explainable; there is no AI.

The technical substance comes from real workflows: two tenant types with overlapping membership, six state machines, capacity/waitlist concurrency, privacy-constrained referral selection, and durable notifications delivered over three channels.

---

## 2. PRD Issues and Recommendations

### 2.1 Contradictions

| Problem | Why it matters | Recommendation |
|---|---|---|
| **Referral is listed as an opportunity type (§6) and as a workflow on a Job (§7, §11).** | Two incompatible models; a "referral opportunity" has no defined fields or actions. | D2: referral = `ReferralRequest` on a Job. A "referral offer" post ("I can refer at X") is post-MVP. |
| **Event lifecycle (`DRAFT→PUBLISHED→REGISTRATION_OPEN…`) overlaps the Opportunity lifecycle (`DRAFT→PUBLISHED→CLOSED/EXPIRED→ARCHIVED`).** | One row cannot hold both; an event past its registration deadline would be "EXPIRED" while the event has not happened. | D3: `Opportunity.status` governs visibility. `EventDetail.event_status` governs registration/outcome. For events, `deadline` closes registration and never expires the opportunity. |
| **Referral states after `REFERRED` duplicate application states; `JOINED` vs `HIRED`.** | Two writers for the same fact will drift. | After `REFERRED`, referral status is written only by the application service in the same transaction (single writer). `HIRED` on the application maps to `JOINED`. |
| **`BLOCKED` is a connection state.** | A block must exist without a prior connection, is directional, and must survive connection deletion. | D6: separate `UserBlock(blocker, blocked)`. |
| **Monetization is "future" but `subscriptions` is in the table list and CLAUDE.md entity list.** | Building billing tables with no billing is the artificial complexity CLAUDE.md forbids. | D7: do not create it. |
| **"Organizer verified" and an "Event Organizer" role exist, but there is no organizer entity.** | A global role with no scope cannot be authorized. | No global organizer role. Event management derives from opportunity ownership (creator / org `RECRUITER+` / community admin). Per-event check-in staff is a should-have. |
| **PRD phases put real-time at 7 and audit at 8**, but applications (3) and referrals (5) must notify and audit. | Retro-fitting notifications/audit into finished state machines causes rework. | D9: audit in Phase 0, notification service + socket in Phase 4. |

### 2.2 Ambiguities

| Problem | Recommendation |
|---|---|
| **"Audience"** on an opportunity is undefined. | Audience = `visibility` (`PUBLIC`, `COMMUNITY`, `ORGANIZATION`) + community distribution rows. No targeting-criteria table (`OpportunityAudience`) in MVP. |
| **"Only eligible users may be selected"** for referral. | Eligible referrer = accepted connection of the requester **and** active member of the job's organization **and** has "accept referral requests" on **and** no block in either direction **and** their org membership is visible to connections. |
| **Privacy levels** — per profile or per field? "Community members" of what? | One profile-level `visibility` plus section flags (contact, experience/education). "Community members" = viewer shares at least one active community. Lists/search always return only the public card (name, photo, headline). |
| **"Application method"** on a Job. | `INTERNAL` (pipeline on platform) or `EXTERNAL_URL` (click-out, no pipeline, no referral tracking). MVP builds `INTERNAL`; `EXTERNAL_URL` is a should-have. |
| **Application content** is never specified. | Resume (PDF, private storage), optional cover note, snapshot of profile headline. Screening questions are post-MVP. |
| **Application transitions**: skipping? backward? re-apply? | Forward-only, skipping allowed, no backward moves. `REJECTED` (recruiter) and `WITHDRAWN` (applicant) from any non-terminal state. Terminal states are final; one application per (job, applicant) ever. |
| **Community join/posting policies** not defined. | `join_policy`: `OPEN` / `APPROVAL` / `INVITE_ONLY`. `posting_policy`: `ADMINS_ONLY` / `MEMBERS_WITH_APPROVAL` / `MEMBERS_AUTO`. |
| **Interests** — what do they match against? | One `Skill` taxonomy; `UserSkill.kind` is `HAS` or `INTERESTED`. Opportunity skills match `HAS` (+5) or `INTERESTED` (+3). |
| **Location** as free text. | Structured `country_code`, `region`, `city` + `work_mode`. No PostGIS. |
| **"Share"** action. | Copy link / send in a message. Only a counter is tracked; no share entity. |
| **"Popular" sort and "Views"** need counters. | `OpportunityStats` row fed from Redis counters by Celery. Popular sort ships in the analytics phase. |
| **Waitlist promotion** policy. | FIFO by `waitlisted_at`, automatic on cancellation or capacity increase, in the same transaction. |
| **Who may message whom.** | Accepted connections only (plus existing conversations). Unrestricted DMs are a spam vector. |
| **Editing a published opportunity.** | Type, organization, and application method are immutable. Other edits are allowed and audited; applicants are not re-notified. |

### 2.3 Missing but essential

| Missing | Recommendation |
|---|---|
| Organization and community **invitations** (PRD has notifications for them but no model). | `OrganizationInvitation` / `CommunityInvitation` with hashed single-use token, expiry, target email. |
| **Last-owner rule** and ownership transfer. | An org/community always has ≥1 active `OWNER`; explicit transfer endpoint. |
| **Organization follow** (feed and relevance refer to it). | `OrganizationFollow` — should-have; its +1 weight contributes 0 until then. |
| **Saved opportunities** table. | `SavedOpportunity(user, opportunity)`. |
| **Status history** for applications/referrals/registrations. | Append-only `*StatusHistory` tables; funnels are computed from them. |
| **Rate limits and idempotency** rules. | Scoped throttles (§16); natural-key idempotency via unique constraints; `client_id` on messages. |
| **Account deactivation / deletion.** | Deactivate + anonymize (should-have); never hard-delete rows referenced by audit or applications. |
| **Event time zones.** | Store `start_at`/`end_at` in UTC plus IANA `timezone` for display and reminders. |
| **Content format / XSS.** | Descriptions are plain text with a restricted Markdown subset rendered client-side without raw HTML. |
| **Notification fan-out** for "followed-community opportunity". | No synchronous fan-out. Opt-in only, chunked Celery fan-out; default is the feed (and later the digest). |
| **Message reporting** (CLAUDE.md mentions; PRD omits). | Not in MVP — it needs a moderator-reads-private-messages policy. MVP offers block. |

### 2.4 Too large for MVP

Project and Mentorship types (D1), community discussions/resources, project workspace, analytics funnels beyond simple counts, opportunity digests, premium tiers, domain verification, reputation, full admin dashboard (Django admin covers user/org/community listing; a custom UI is built only for the moderation queue and stats).

### 2.5 Architectural and scalability concerns

- **Relevance scoring over all opportunities per request** does not scale. Score is computed in SQL over a pre-filtered candidate set (visible, published, last 90 days) with the user's skill/community IDs passed as literals.
- **Per-item Celery ETA tasks** (one reminder task per event) are fragile on a Redis broker (visibility-timeout redelivery, lost on flush). All time-based work uses periodic sweepers over indexed columns.
- **Notification loss** if the broker is down after commit. The `Notification` row is written inside the business transaction; delivery is enqueued `on_commit`, and a sweeper re-dispatches undelivered rows (a lightweight outbox).
- **Channels layer is at-most-once.** The socket is a hint; REST is the truth. Clients dedupe by ID and refetch on reconnect.

---

## 3. Final Architecture

```text
Browser (React SPA)
   │ HTTPS /api/v1/*            │ WSS /ws/stream/
   ▼                            ▼
              Nginx (TLS, static SPA, body limits, request id)
   │                            │
   ▼                            ▼
 api (gunicorn+uvicorn, DRF)   ws (daphne, Channels consumers)     ← same image, two processes
   │                            │
   └──────── services / selectors / policies (per domain app) ─────┘
        │                │                    │
   PostgreSQL        Redis                 Celery worker(s) + beat
 (source of truth)  db0 cache/throttle/     queues: default, email,
                    tickets/counters        notifications, scheduled, analytics
                    db1 Celery broker            │
                    db2 channel layer       SMTP provider, S3-compatible storage
```

**Backend layout** (one Django app per domain, no `core`):

```text
backend/
├── config/            settings (base/dev/test/prod), urls, asgi, celery
├── common/            base models, errors, pagination, state machine helper, request-id, storage, throttles
├── audit/             AuditLog + record()
├── users/             User, UserProfile, experience/education, tokens, blocks
├── taxonomy/          Skill                      (addition to CLAUDE.md's suggested list)
├── organizations/     Organization, OrganizationMember, OrganizationInvitation
├── communities/       Community, CommunityMember, CommunityInvitation, CommunityRule
├── opportunities/     Opportunity, OpportunitySkill, OpportunityCommunity, SavedOpportunity, search, feed
├── jobs/              JobDetail
├── applications/      Application, ApplicationStatusHistory
├── events/            EventDetail, EventRegistration
├── connections/       Connection
├── referrals/         ReferralRequest, ReferralStatusHistory
├── messaging/         Conversation, ConversationParticipant, Message
├── notifications/     Notification, NotificationDelivery, NotificationPreference, consumer
├── moderation/        Report, ModerationAction, UserRestriction
└── analytics/         OpportunityStats, DailyOpportunityStats
```

**Layering inside every app** — the rule that keeps authorization and transactions in one place:

| File | Responsibility |
|---|---|
| `models.py` | Schema, constraints, indexes. No business logic. |
| `policies.py` | Pure `can_<action>(actor, obj) -> bool`. The only place permission rules live. |
| `selectors.py` | Read queries; `QuerySet.visible_to(user)` scoping. |
| `services.py` | All writes and state transitions; owns `transaction.atomic`, locking, audit, notification calls. |
| `api/` | Serializers (validation/shape only), views (call policy → service), urls. |
| `tasks.py` | Thin Celery wrappers over services. |

Cross-app reactions are explicit service calls (e.g. `applications.services.transition()` calls `referrals.services.sync_from_application()`), not Django signals. `audit` and `notifications` are leaves that never import domain apps.

**Version pins** are fixed in Phase 0: current Django LTS, DRF, Channels + `channels_redis`, Celery, PostgreSQL 17, Redis 7, Python 3.13+, Node LTS.

---

## 4. Domain Model

### 4.1 Opportunity modeling decision — Option B

**Chosen: a base `Opportunity` table + explicit one-to-one detail tables** (`JobDetail`, `EventDetail`, later `ProjectDetail`, `MentorshipDetail`) whose primary key is `opportunity_id`.

| Option | Verdict |
|---|---|
| A. One wide table with nullable fields | Rejected. No `NOT NULL`/check constraints per type; grows with every new type; forbidden by CLAUDE.md. |
| **B. Base + explicit one-to-one detail** | **Chosen.** Feed/search/visibility/distribution/moderation query one narrow table. Type-specific constraints are real. Adding a type is one new table. Joins are explicit (`select_related('job_detail')`). |
| C. Django multi-table inheritance | Rejected. Same tables as B, but implicit joins, awkward polymorphic querysets, and accidental parent/child saves. |
| D. JSONB attributes per type | Rejected. Loses constraints, indexes, and typed filters (experience level, capacity, dates). |

Invariants: `type` is immutable after creation; base and detail rows are created in one transaction by the service; publish validates that the matching detail row exists. Because the detail PK equals the opportunity ID, `/jobs/{id}/apply/` and `/events/{id}/register/` use the opportunity ID.

### 4.2 Conventions

- Primary keys are time-ordered UUIDs (UUIDv7) exposed in URLs: non-enumerable, index-friendly. Authorization is still mandatory on every object.
- Every table has `created_at`; mutable tables have `updated_at`.
- Emails are stored lowercased with a unique index on `Lower(email)`.
- Enumerations are `TextChoices` with a DB `CHECK` constraint.
- Polymorphic targets: `Report`/`ModerationAction` use nullable FKs with `CHECK (num_nonnulls(...) = 1)` (integrity matters). `AuditLog`/`Notification` use `(target_type, target_id)` without an FK (must survive deletion).

### 4.3 Entities

**Identity**

| Entity | Purpose / key fields | Relationships, ownership, tenant | Constraints | Indexes |
|---|---|---|---|---|
| **User** | Login identity. `email`, `password`, `email_verified_at`, `platform_role` (`USER`/`MODERATOR`/`ADMIN`), `is_active`, `suspended_until` | Global. Owns itself. | unique `Lower(email)` | `Lower(email)` |
| **UserProfile** | 1:1 with User. `display_name`, `headline`, `bio`, `avatar`, `country_code`, `region`, `city`, `work_mode_preference`, `experience_level`, `visibility`, `show_contact`, `show_history`, `accepts_referral_requests` | Owned by user. Global, privacy-filtered. | check on enums | trigram on `display_name`; `(country_code, city)` |
| **UserExperience / UserEducation** | Profile history rows | FK user | `end_date >= start_date` | `(user)` |
| **Skill** | Shared taxonomy. `name`, `slug` | Global, admin-curated + user-suggested | unique `slug`, unique `Lower(name)` | trigram on `name` |
| **UserSkill** | `user`, `skill`, `kind` (`HAS`/`INTERESTED`) | | unique `(user, skill, kind)` | `(user, kind, skill)` |
| **UserBlock** | `blocker`, `blocked` | Directional | unique pair; `blocker != blocked` | `(blocked)` |

**Tenants**

| Entity | Purpose / key fields | Relationships, ownership, tenant | Constraints | Indexes |
|---|---|---|---|---|
| **Organization** | Tenant. `name`, `slug`, `description`, `website`, `industry`, location, `logo`, `verification_status` (`UNVERIFIED`/`PENDING`/`VERIFIED`/`REJECTED`), `status` (`ACTIVE`/`SUSPENDED`) | Owned by its `OWNER` members | unique `slug` | trigram on `name`; `(verification_status)` |
| **OrganizationMember** | `organization`, `user`, `role` (`OWNER`/`ADMIN`/`RECRUITER`/`MEMBER`), `status` (`ACTIVE`/`REMOVED`/`LEFT`), `is_public`, `joined_at` | Tenant = organization. A user has many. | unique `(organization, user)` | `(user, status)`, `(organization, status, role)` |
| **OrganizationInvitation** | `organization`, `email`, `role`, `token_hash`, `invited_by`, `status` (`PENDING`/`ACCEPTED`/`DECLINED`/`REVOKED`/`EXPIRED`), `expires_at` | Tenant = organization | unique `(organization, Lower(email))` where `status='PENDING'`; unique `token_hash` | `(Lower(email), status)` |
| **Community** | Tenant. `name`, `slug`, `description`, `category`, `logo`, `cover`, `join_policy`, `posting_policy`, `visibility` (`PUBLIC`/`PRIVATE`), `is_verified`, `status` | Owned by its `OWNER` members | unique `slug` | trigram on `name`; `(category)` |
| **CommunityMember** | `community`, `user`, `role` (`OWNER`/`ADMIN`/`MODERATOR`/`MEMBER`), `status` (`PENDING`/`INVITED`/`ACTIVE`/`REJECTED`/`LEFT`/`REMOVED`/`BANNED`), `notify_new_opportunities` | Tenant = community. One row per pair, reused on rejoin. | unique `(community, user)` | `(user, status)`, `(community, status, role)` |
| **CommunityRule** | `community`, `position`, `title`, `body` | | unique `(community, position)` | |

**Opportunities**

| Entity | Purpose / key fields | Relationships, ownership, tenant | Constraints | Indexes |
|---|---|---|---|---|
| **Opportunity** | Base. `type`, `creator`, `organization?`, `title`, `description`, `status`, `visibility`, `moderation_status` (`VISIBLE`/`HIDDEN`/`REMOVED`), `work_mode`, `country_code`, `region`, `city`, `deadline?`, `published_at?`, `closed_at?`, `close_reason?`, `search_vector`, `skills_text` | Owner = organization if set, otherwise creator. | `published_at IS NOT NULL` when status ≠ `DRAFT`; `visibility='ORGANIZATION'` requires `organization` | Partial `(published_at DESC, id)` where published and visible; `(type, status, deadline)`; `(organization, status)`; `(creator, status)`; partial `(deadline)` where `status='PUBLISHED'`; GIN `search_vector`; GIN trigram `title`; `(country_code, city)` |
| **OpportunitySkill** | `opportunity`, `skill` | | unique pair | `(skill, opportunity)` |
| **OpportunityCommunity** | Distribution. `opportunity`, `community`, `status` (`PENDING`/`APPROVED`/`REJECTED`/`REMOVED`), `submitted_by`, `reviewed_by`, `reviewed_at`, `rejection_reason`, `is_featured`, `featured_until` | Tenant = community (the community owns the decision) | unique `(opportunity, community)` | `(community, status, created_at)`; partial `(community, is_featured)` where approved |
| **SavedOpportunity** | `user`, `opportunity` | Owned by user | unique pair | `(user, created_at DESC)` |
| **JobDetail** | PK = opportunity. `department`, `employment_type`, `experience_level`, `salary_min/max/currency/period`, `application_method`, `external_url?`, `openings` | Tenant via opportunity | `salary_min <= salary_max`; `external_url` required iff external; `openings >= 1` | `(experience_level)`, `(employment_type)` |
| **EventDetail** | PK = opportunity. `event_status`, `start_at`, `end_at`, `timezone`, `format` (`IN_PERSON`/`ONLINE`/`HYBRID`), `venue`, `online_url`, `capacity?`, `confirmed_count`, `registration_opens_at?`, `attendee_visibility`, `image`, `reminder_24h_sent_at`, `reminder_1h_sent_at` | Tenant via opportunity | `end_at > start_at`; `confirmed_count >= 0`; `capacity IS NULL OR confirmed_count <= capacity` | `(start_at)`, `(event_status, start_at)` |

**Actions on opportunities**

| Entity | Purpose / key fields | Relationships, ownership, tenant | Constraints | Indexes |
|---|---|---|---|---|
| **Application** | `opportunity` (job), `applicant`, `status`, `resume`, `cover_note`, `referral?`, `status_changed_at` | Visible to applicant and to managers of the job's owner | unique `(opportunity, applicant)` | `(opportunity, status, created_at)`, `(applicant, created_at DESC)` |
| **ApplicationStatusHistory** | `application`, `from_status`, `to_status`, `actor?`, `note`, `created_at` | Append-only | | `(application, created_at)` |
| **EventRegistration** | `event`, `user`, `status` (`CONFIRMED`/`WAITLISTED`/`CANCELLED`), `waitlisted_at?`, `checkin_token_hash`, `checked_in_at?`, `checked_in_by?` | Visible to registrant and event managers | unique `(event, user)`; unique `checkin_token_hash`; `checked_in_at` only when `CONFIRMED` | `(event, status, waitlisted_at)`, `(user, created_at DESC)` |
| **Connection** | `user_low`, `user_high`, `requested_by`, `status` (`REQUESTED`/`ACCEPTED`/`DECLINED`), `responded_at` | Owned jointly; never listable for third parties | `user_low < user_high`; unique `(user_low, user_high)`; `requested_by` is one of the pair | `(user_low, status)`, `(user_high, status)` |
| **ReferralRequest** | `opportunity` (job), `requester`, `referrer`, `message`, `status`, `endorsement_note?`, `application?`, `responded_at`, `expires_at` | Visible to requester and referrer; to job managers only from `REFERRED` on | unique `(opportunity, requester, referrer)`; `requester != referrer` | `(referrer, status, created_at)`, `(requester, status, created_at)`, `(opportunity, status)`; partial `(expires_at)` where `REQUESTED` |
| **ReferralStatusHistory** | As application history | Append-only | | `(referral, created_at)` |

**Communication**

| Entity | Purpose / key fields | Relationships, ownership, tenant | Constraints | Indexes |
|---|---|---|---|---|
| **Conversation** | 1:1 thread. `user_low`, `user_high`, `last_message_at`, `last_message_preview` | Participants only | `user_low < user_high`; unique pair | `(user_low, last_message_at DESC)`, `(user_high, last_message_at DESC)` |
| **ConversationParticipant** | `conversation`, `user`, `last_read_message_id?`, `last_read_at?`, `muted` | Kept (PRD `conversation_members`) so group chat needs no remodel | unique `(conversation, user)` | `(user)` |
| **Message** | `conversation`, `sender`, `body`, `client_id`, `created_at` | Immutable in MVP | unique `(conversation, sender, client_id)`; body length check | `(conversation, id)` |
| **Notification** | `recipient`, `type`, `actor?`, `target_type`, `target_id`, `payload` (minimal JSON), `dedupe_key?`, `read_at?` | Recipient only | unique `(recipient, dedupe_key)` where not null | `(recipient, created_at DESC)`; partial `(recipient)` where `read_at IS NULL` |
| **NotificationDelivery** | `notification`, `channel` (`EMAIL`), `status` (`PENDING`/`SENT`/`FAILED`/`SKIPPED`), `attempts`, `sent_at` | | unique `(notification, channel)` | partial `(created_at)` where `PENDING` |
| **NotificationPreference** | `user`, `category`, `in_app`, `email` | Missing row = defaults | unique `(user, category)` | |

**Trust**

| Entity | Purpose / key fields | Relationships, ownership, tenant | Constraints | Indexes |
|---|---|---|---|---|
| **Report** | `reporter`, target FKs (user / organization / community / opportunity), `category`, `description`, `status`, `scope_community?`, `assigned_to?`, `resolved_at`, `resolution_note` | `scope_community` set → community admins review; otherwise platform moderators | exactly one target; unique `(reporter, target)` where status is open | `(status, created_at)`, `(scope_community, status)`, per-target |
| **ModerationAction** | `actor`, `action_type` (`HIDE`/`REMOVE`/`WARN`/`SUSPEND`/`RESTRICT_POSTING`/`VERIFY`/`UNVERIFY`), target FKs, `report?`, `scope_community?`, `reason`, `expires_at?`, `reverted_at?`, `reverted_by?` | Append-only apart from revert fields | exactly one target | `(target…, created_at)`, `(actor, created_at)` |
| **UserRestriction** | `user`, `type` (`POSTING`/`MESSAGING`), `until?`, `source_action` | Checked by policies | | `(user, type)` |
| **AuditLog** | `actor?`, `actor_type` (`USER`/`SYSTEM`), `action` (e.g. `application.status_changed`), `target_type`, `target_id`, `organization_id?`, `community_id?`, `metadata` JSONB, `ip?`, `request_id`, `created_at` | Append-only; platform admins read all, org/community owners read their tenant's | no update/delete path in code; DB trigger blocks them (hardening) | `(target_type, target_id, created_at)`, `(actor, created_at)`, `(organization_id, created_at)`, `(community_id, created_at)`, `(action, created_at)` |
| **OpportunityStats / DailyOpportunityStats** | Denormalized counters: views, saves, applications, registrations, referrals, `popularity_score` | Derived, rebuildable | unique `(opportunity, date)` on daily | `(popularity_score DESC)` |

Deferred entities: `ProjectDetail`, `ProjectMember`, `MentorshipDetail`, `MentorshipRequest`, `OrganizationFollow`, `EventStaff`, `Subscription`.

---

## 5. Database Design

- **Extensions**: `pg_trgm`, `unaccent`, enabled in the first migration of `common`.
- **Custom User model exists in the very first migration.** Changing `AUTH_USER_MODEL` later is prohibitively expensive.
- **Deletion policy**: `PROTECT` on FKs from applications, registrations, referrals, messages, moderation actions; `CASCADE` only for pure join rows (skills, saved, preferences). Users are deactivated/anonymized, not deleted. Only `DRAFT` opportunities can be hard-deleted.
- **Constraints are the last line of defence**, the service layer is the first: every uniqueness and capacity rule above is enforced by both.
- **Counters** (`confirmed_count`, stats) are changed only with `F()` expressions or under a row lock.
- **Search column**: `search_vector` is a stored `tsvector` maintained by `opportunities.services.reindex()` on create/update/skill change (a generated column cannot reach skills and organization name). Organization rename enqueues a reindex of its opportunities.
- **Pagination**: keyset (cursor) on `(published_at, id)` / `(created_at, id)` for all chronological lists; no unbounded endpoints; page size capped at 50.
- **Migrations**: one per schema change, reviewed for locking; indexes on existing large tables use `CREATE INDEX CONCURRENTLY` once data exists.

---

## 6. State Machines

**Shared mechanics.** `common/state_machine.py` holds a declarative table per machine: `(from, to) → {policy, guard}`. Every transition runs in one service function:

1. `transaction.atomic()` and `SELECT … FOR UPDATE` on the row.
2. Re-read the current state; reject if `(current, target)` is not in the table → `409 invalid_transition`.
3. If the client sent `expected_status` and it differs → `409 stale_state`.
4. Check policy (→ `403`) and guard (→ `422`).
5. Update the row, insert a history row, insert the `AuditLog` row, insert `Notification` rows.
6. `transaction.on_commit` enqueues delivery (socket push, email).

Anything not listed as valid below is invalid. Repeating a transition that already happened returns the current resource with `200` (idempotent) when the target state equals the current state and the actor is permitted.

### 6.1 Opportunity

States: `DRAFT`, `PUBLISHED`, `CLOSED`, `EXPIRED`, `ARCHIVED`. `moderation_status` is orthogonal (a hidden opportunity keeps its lifecycle state).

| Transition | Who | Guards | Side effects / notifications / audit |
|---|---|---|---|
| create → `DRAFT` | Verified user (personal) or org `RECRUITER+` | Not posting-restricted; org `ACTIVE` | `opportunity.created` |
| `DRAFT → PUBLISHED` | Manager | Required fields + detail row valid; deadline in future; event dates valid | Set `published_at`; build search vector; create `OpportunityCommunity` rows (`APPROVED` or `PENDING` per policy); notify community admins of pending reviews; opt-in member fan-out; `opportunity.published` |
| `PUBLISHED → CLOSED` | Manager; system (event completed/cancelled) | `close_reason` required | New applies/registrations rejected; open referral requests → `CLOSED`; event cancel notifies registrants; `opportunity.closed` |
| `PUBLISHED → EXPIRED` | System only | `deadline < now` and type ≠ event | Same as close for referrals; notify manager; `opportunity.expired` |
| `CLOSED/EXPIRED → ARCHIVED` | Manager; system after 90 days | — | Removed from all public lists; `opportunity.archived` |
| delete | Manager | Only `DRAFT` | `opportunity.deleted` |

Invalid: any transition out of `ARCHIVED`; `CLOSED/EXPIRED → PUBLISHED` (MVP offers "duplicate as draft"; reopen is a should-have); `DRAFT → CLOSED`.
Races: publish vs edit, close vs expire sweeper — the sweeper uses `UPDATE … WHERE status='PUBLISHED' AND deadline < now()`, so a manual close wins cleanly. Apply/register always re-check status and deadline themselves and do not depend on the sweeper having run.

### 6.2 Job Application

States: `APPLIED → SCREENING → SHORTLISTED → INTERVIEW → OFFER → HIRED`; `REJECTED`; `WITHDRAWN`. Terminal: `HIRED`, `REJECTED`, `WITHDRAWN`.

| Transition | Who | Guards | Side effects / notifications / audit |
|---|---|---|---|
| create → `APPLIED` | Verified user | Job `PUBLISHED`, visible to user, deadline not passed, `INTERNAL` method, not the job's manager, no block/suspension | Link a `REFERRED` referral if one exists; notify recruiters (in-app); `application.submitted` |
| forward move (any later pipeline stage) | Job manager (org `RECRUITER+` or personal creator) | Target is strictly later | History; notify applicant (in-app + email); sync referral; `application.status_changed` |
| → `REJECTED` | Job manager | From any non-terminal | Notify applicant; referral → `CLOSED` |
| → `WITHDRAWN` | Applicant | From any non-terminal | Notify recruiters; referral → `CLOSED` |

Invalid: backward moves; anything from a terminal state; applicant changing pipeline stage; recruiter withdrawing.
Races: duplicate apply (double click, two tabs) → unique `(opportunity, applicant)`; `IntegrityError` is caught and the existing application returned. Two recruiters moving the same card → row lock + `expected_status`. Reaching `openings` hires prompts the recruiter to close the job; it is not closed automatically.

### 6.3 Referral

States: `REQUESTED`, `ACCEPTED`, `DECLINED`, `CANCELLED`, `EXPIRED`, `REFERRED`, `APPLICATION_SUBMITTED`, `INTERVIEW`, `OFFER`, `JOINED`, `CLOSED`.

| Transition | Who | Guards | Side effects / notifications / audit |
|---|---|---|---|
| create → `REQUESTED` | Requester | Job `PUBLISHED`, org-owned, internal method; referrer eligible (§2.2); no existing request to this referrer for this job; ≤3 active requests per job; daily throttle | Notify referrer (in-app + email); `referral.requested` |
| `REQUESTED → ACCEPTED` / `DECLINED` | Referrer only | — | Notify requester; decline carries no reason; `referral.accepted/declined` |
| `REQUESTED → CANCELLED` | Requester | — | Remove referrer's pending notification |
| `REQUESTED → EXPIRED` | System | 14 days without response | Notify requester |
| `ACCEPTED → REFERRED` | Referrer | Still an active member of the org; endorsement note | Becomes visible to recruiters; if requester already applied, link and move straight to the mirrored state; notify requester; `referral.referred` |
| `REFERRED → APPLICATION_SUBMITTED` | System (application created) | — | Notify referrer |
| `→ INTERVIEW / OFFER / JOINED` | System (application reaches `INTERVIEW` / `OFFER` / `HIRED`) | — | Notify referrer on `JOINED`; `referral.outcome` |
| `ACCEPTED / REFERRED / later → CLOSED` | System (application rejected/withdrawn, job closed); referrer may back out from `ACCEPTED` | — | Notify the other party |

Invalid: any user-driven transition after `REFERRED`; accept/decline by anyone but the referrer; acting on `DECLINED`/`CANCELLED`/`EXPIRED`/`JOINED`/`CLOSED`.
Races: accept vs cancel vs expiry → row lock, first writer wins, the loser gets `409`. Concurrent creates exceeding the per-job cap → `pg_advisory_xact_lock(hash(requester, opportunity))` around count-and-insert.

### 6.4 Event

`Opportunity.status` supplies `DRAFT`/`PUBLISHED`. `EventDetail.event_status`: `SCHEDULED`, `REGISTRATION_OPEN`, `REGISTRATION_CLOSED`, `COMPLETED`, `CANCELLED`.

| Transition | Who | Guards | Side effects / notifications / audit |
|---|---|---|---|
| publish → `SCHEDULED` or `REGISTRATION_OPEN` | Manager | Open immediately unless `registration_opens_at` is in the future | As opportunity publish |
| `SCHEDULED → REGISTRATION_OPEN` | System at `registration_opens_at`; manager | Before `start_at` | `event.registration_opened` |
| `REGISTRATION_OPEN → REGISTRATION_CLOSED` | System at `deadline` or `start_at`; manager | — | `event.registration_closed` |
| `REGISTRATION_CLOSED → REGISTRATION_OPEN` | Manager | Before `start_at` and deadline not passed (addition to the PRD's linear flow) | Audit |
| `→ COMPLETED` | System at `end_at` | Not cancelled | Opportunity → `CLOSED (COMPLETED)`; attendance frozen |
| `→ CANCELLED` | Manager | Before `COMPLETED` | Opportunity → `CLOSED (CANCELLED)`; notify all confirmed + waitlisted (in-app + email); `event.cancelled` |

Reaching capacity does not change state: further registrations are waitlisted.

**Registration sub-machine**: `CONFIRMED`, `WAITLISTED`, `CANCELLED`; attended = `checked_in_at` set.

| Transition | Who | Notes |
|---|---|---|
| register → `CONFIRMED` / `WAITLISTED` | Verified user | Event `REGISTRATION_OPEN`; decided under the event row lock (§17) |
| `WAITLISTED → CONFIRMED` | System | FIFO promotion on cancellation or capacity increase; notify (in-app + email) |
| `CONFIRMED / WAITLISTED → CANCELLED` | Registrant; manager | Before `start_at`; triggers promotion |
| `CANCELLED → CONFIRMED / WAITLISTED` | Registrant | Re-register reuses the row, goes to the back of the queue, new check-in token |
| check-in | Event manager | `CONFIRMED`, within check-in window, valid token; conditional update makes it single-use |

### 6.5 Community Membership

States: `PENDING`, `INVITED`, `ACTIVE`, `REJECTED`, `LEFT`, `REMOVED`, `BANNED`.

| Transition | Who | Notes / effects |
|---|---|---|
| join → `ACTIVE` | User | `join_policy=OPEN` |
| join → `PENDING` | User | `join_policy=APPROVAL`; notify admins |
| invite → `INVITED` | Community `ADMIN+` | Notify invitee |
| `PENDING → ACTIVE` / `REJECTED` | Community `ADMIN+` (`MODERATOR` may approve) | Notify user |
| `INVITED → ACTIVE` / `LEFT` | Invitee | — |
| `ACTIVE → LEFT` | Member | Blocked for the last `OWNER` |
| `ACTIVE → REMOVED` / `BANNED` | `ADMIN+`; only `OWNER` acts on `ADMIN` | Their pending submissions are rejected |
| `LEFT / REJECTED / REMOVED → PENDING / ACTIVE` | User (re-join) | Row reused |
| `BANNED → REMOVED` (unban) | `ADMIN+` | User may then re-join |
| role change | `OWNER` any; `ADMIN` between `MODERATOR`/`MEMBER` | No self-promotion; last-owner rule |

All role and status changes write `community.membership_changed`.

### 6.6 Organization Membership

Invitation: `PENDING → ACCEPTED / DECLINED / REVOKED / EXPIRED`. Membership: `ACTIVE → LEFT / REMOVED`, and back to `ACTIVE` only through a new invitation. Organizations are never open-join.

| Transition | Who | Notes / effects |
|---|---|---|
| create organization | Verified user | Creator becomes `OWNER` in the same transaction |
| invite | `ADMIN+` (`ADMIN` may invite `RECRUITER`/`MEMBER` only) | Email + in-app if the email belongs to a user |
| accept / decline | Authenticated user whose **verified** email equals the invited email | Token is single-use (conditional update) |
| revoke | `ADMIN+` | — |
| role change | `OWNER` any role; `ADMIN` between `RECRUITER`/`MEMBER` | No self-promotion; cannot demote the last `OWNER` |
| remove | `OWNER` any; `ADMIN` removes `RECRUITER`/`MEMBER` | Their opportunities stay with the organization |
| leave | Member | Blocked for the last `OWNER` |
| transfer ownership | `OWNER` | Target must be `ACTIVE`; atomic |

All write `organization.membership_changed` / `organization.role_changed`. Races: every role/removal mutation first locks the `Organization` row, then counts owners, so two owners demoting each other cannot leave zero.

---

## 7. Authorization and Multi-Tenancy

**Tenancy model**: logical tenancy through foreign keys and scoped querysets in one schema. No schema-per-tenant and no PostgreSQL RLS — tenants here overlap by design (one opportunity in many communities), which those mechanisms model poorly.

**Three independent role dimensions** — never a single `user.role` or `user.organization`:

| Dimension | Stored in | Hierarchy |
|---|---|---|
| Platform | `User.platform_role` | `ADMIN > MODERATOR > USER` |
| Organization | `OrganizationMember.role` (per org) | `OWNER > ADMIN > RECRUITER > MEMBER` |
| Community | `CommunityMember.role` (per community) | `OWNER > ADMIN > MODERATOR > MEMBER` |

"Recruiter" is an organization role. "Event organizer" is derived (manager of an event opportunity). "Moderator" exists at platform level and per community. Platform roles do not grant tenant powers implicitly: a platform admin acts on tenant resources only through moderation/admin endpoints, which are audited.

**Resource scoping**

| Scope | Resources |
|---|---|
| Globally visible (subject to status/privacy) | Public opportunities, organizations, public communities, skills, public profile cards |
| Organization-scoped | Members, invitations, applications to the org's jobs, org-visibility opportunities, org audit log, org stats |
| Community-scoped | Members, join requests, distribution rows and review queue, community-scoped reports, community audit log |
| User-private | Applications, registrations, referral requests (two parties), connections, conversations, notifications, saved items, preferences |
| Platform-only | Platform reports, moderation actions, full audit log, verification |

**Enforcement pattern**

1. **Lists** are scoped by queryset: `Model.objects.visible_to(user)`. A list endpoint never filters in Python and never relies on per-object checks.
2. **Detail and mutations** fetch through the same scoped queryset (invisible → `404`, hiding existence), then call `policies.can_<action>(user, obj)` (visible but not allowed → `403`).
3. **Services re-check** resource state under lock; views never mutate models directly.
4. Policies load a per-request memoized membership map (two queries: the user's org memberships and community memberships).
5. Suspended users and inactive tenants are rejected centrally (authentication class + policy helpers).

**Opportunity visibility** (`visible_to`, implemented with `Exists` subqueries):

```text
manager(user, opp)                                         -- creator, or org RECRUITER+
OR platform moderator
OR ( status IN (PUBLISHED, CLOSED, EXPIRED) AND moderation_status = VISIBLE AND (
       visibility = PUBLIC
    OR visibility = COMMUNITY    AND EXISTS approved distribution to a community where user is ACTIVE
    OR visibility = ORGANIZATION AND user is ACTIVE member of opp.organization ) )
```

**Opportunity ownership**: organization-owned opportunities are managed by any `RECRUITER+` of that organization (not only the creator); `MEMBER` has read access to org-visibility items only. Personal opportunities are managed by their creator.

**Cross-community distribution**

- Submitting to a community requires: actor manages the opportunity **and** is an `ACTIVE` member of that community **and** satisfies its `posting_policy`.
- Each community approves independently; one rejection does not affect other communities or the global listing.
- A community feed shows only `APPROVED` rows. Community `MODERATOR+` can approve, reject, remove, feature.
- Removing from a community (`REMOVED`) is a community decision; hiding globally is a platform moderation action.
- A `COMMUNITY`-visibility opportunity with no approved distribution is visible only to its managers; the UI states this.

**Permission-aware responses**: detail payloads include a `viewer` block computed by the same policies (`can_edit`, `can_apply`, `has_applied`, `can_request_referral`, …). The frontend renders from it and never re-implements rules.

---

## 8. API Architecture

**Conventions** (base path `/api/v1/`)

- JSON; `Authorization: Bearer <access>`; cursor pagination `{results, next, previous}`; `?page_size` ≤ 50.
- Errors use one envelope (problem-details style): `{type, title, status, code, detail, errors: {field: [..]}, request_id}`.
- Status codes: `400` malformed, `401` unauthenticated, `403` forbidden, `404` not found or not visible, `409` conflict (duplicate, invalid/stale transition, capacity), `422` business-rule validation, `429` throttled.
- CRUD for plain resources; **explicit `POST` action endpoints for every state transition**. `status` is read-only on every serializer.
- OpenAPI schema generated with drf-spectacular; frontend types are generated from it.
- "Auth" column: `P` public, `U` authenticated, `V` authenticated + verified email.

### Auth and users

| Method & path | Purpose | Auth | Notes / errors |
|---|---|---|---|
| `POST /auth/register/` | Create account, send verification | P | Uniform response (no account enumeration); `429` |
| `POST /auth/verify-email/` · `/resend/` | Confirm email | P | Single-use signed token; `400` expired |
| `POST /auth/login/` | Returns access token; sets refresh cookie | P | Throttled per IP + email; generic `401` |
| `POST /auth/refresh/` | Rotate refresh, new access | cookie | Reuse of a rotated token revokes the family; `401` |
| `POST /auth/logout/` | Revoke refresh | U | |
| `POST /auth/password-reset/` · `/confirm/` · `POST /auth/password-change/` | Reset / change | P / U | Revokes all sessions |
| `POST /auth/ws-ticket/` | 30 s single-use socket ticket | U | |
| `GET, PATCH /users/me/` | Own account + profile + memberships + roles | U | |
| `PUT /users/me/skills/` | Replace skill sets | U | |
| `GET /users/{id}/` | Profile filtered by privacy | U | `404` if not visible |
| `GET, PATCH /users/me/notification-preferences/` | Preferences | U | |
| `GET /skills/?q=` | Autocomplete (trigram) | U | |
| `PUT, DELETE /users/{id}/block/` | Block / unblock | U | |

### Organizations

| Method & path | Purpose | Authorization |
|---|---|---|
| `GET /organizations/` · `GET /organizations/{id}/` | List/search, detail | P |
| `POST /organizations/` | Create (caller becomes owner) | V |
| `PATCH /organizations/{id}/` | Edit | `ADMIN+` |
| `GET /organizations/{id}/members/` | Members (public members to outsiders, all to members) | P / member |
| `POST /organizations/{id}/invitations/` · `DELETE …/{inv}/` | Invite / revoke | `ADMIN+` |
| `POST /organization-invitations/{token}/accept/` · `/decline/` | Respond | Invited verified email |
| `PATCH /organizations/{id}/members/{mid}/` | Change role | Per §6.6; `409 last_owner` |
| `DELETE /organizations/{id}/members/{mid}/` · `POST …/leave/` | Remove / leave | Per §6.6 |
| `POST /organizations/{id}/transfer-ownership/` | Transfer | `OWNER` |
| `GET /organizations/{id}/opportunities/` | Org's opportunities (`?status` for managers) | P / `RECRUITER+` |

### Communities

| Method & path | Purpose | Authorization |
|---|---|---|
| `GET /communities/` · `GET /communities/{id}/` | List/search, detail | P (private: members only) |
| `POST /communities/` · `PATCH /communities/{id}/` | Create / edit | V / `ADMIN+` |
| `POST /communities/{id}/join/` · `/leave/` | Join (→ `ACTIVE` or `PENDING`) / leave | V; `409` banned or already member |
| `GET /communities/{id}/members/?status=&role=` | Members; pending list for admins | Member / `MODERATOR+` |
| `POST /communities/{id}/members/{mid}/approve/` · `reject/` · `remove/` · `ban/` · `unban/` | Membership transitions | Per §6.5 |
| `PATCH /communities/{id}/members/{mid}/` | Role change | Per §6.5 |
| `POST /communities/{id}/invitations/` | Invite | `ADMIN+` |
| `GET /communities/{id}/opportunities/` | Approved feed (featured first) | Per community visibility |
| `GET /communities/{id}/submissions/?status=PENDING` | Review queue | `MODERATOR+` |
| `POST /communities/{id}/submissions/{sid}/approve/` · `reject/` · `remove/` · `feature/` · `unfeature/` | Distribution decisions | `MODERATOR+`; `409` wrong state |

### Opportunities

| Method & path | Purpose | Authorization / notes |
|---|---|---|
| `GET /opportunities/` | Feed + search (§11 parameters) | P; relevance requires U |
| `POST /opportunities/` | Create draft: base fields + `type` + nested `job` or `event` + `organization_id?` + `skill_ids` + `community_ids` | V; org `RECRUITER+` if org-owned |
| `GET /opportunities/{id}/` | Detail with nested detail, communities, `viewer` | Visibility rule |
| `PATCH /opportunities/{id}/` | Edit (restricted set after publish) | Manager |
| `DELETE /opportunities/{id}/` | Delete draft | Manager; `409` if not draft |
| `POST /opportunities/{id}/publish/` | `DRAFT → PUBLISHED` | Manager; `422` with per-field completeness errors; `409` wrong state |
| `POST /opportunities/{id}/close/` `{reason}` · `/archive/` | Close / archive | Manager |
| `POST /opportunities/{id}/communities/` `{community_ids}` | Distribute to more communities | Manager + member of each |
| `PUT, DELETE /opportunities/{id}/save/` | Save / unsave (idempotent) | U |
| `GET /users/me/saved-opportunities/` · `GET /users/me/opportunities/?status=` | Saved; own/managed | U |

Publish response: the full opportunity plus `distributions: [{community, status}]` so the creator sees which communities need approval.

### Jobs and applications

| Method & path | Purpose | Authorization / notes |
|---|---|---|
| `POST /jobs/{id}/apply/` (multipart: `resume`, `cover_note`) | Apply | V. `201` new, `200` existing (idempotent), `409 not_accepting`, `422` invalid file |
| `GET /applications/` | My applications (`?status`) | U |
| `GET /applications/{id}/` | Detail + history | Applicant or job manager |
| `POST /applications/{id}/withdraw/` | Withdraw | Applicant |
| `GET /jobs/{id}/applications/?status=` | Pipeline (with applicant card, referral badge) | Job manager |
| `POST /applications/{id}/transition/` `{to, expected_status, note?}` | Move stage / reject | Job manager; `409 invalid_transition` / `stale_state` |
| `GET /applications/{id}/resume/` | Short-lived signed download URL | Applicant or job manager; audited |

The PRD's `/applications/{id}/status` becomes the `transition` action; `PATCH` never changes status.

### Connections and referrals

| Method & path | Purpose | Authorization / notes |
|---|---|---|
| `GET /connections/?status=&direction=` | **Own** connections only | U |
| `POST /connections/` `{user_id}` | Request | V; `409` existing; blocked → `404`; throttled |
| `POST /connections/{id}/accept/` · `/decline/` | Respond | Recipient only |
| `DELETE /connections/{id}/` | Remove / cancel request | Either party |
| `GET /jobs/{id}/eligible-referrers/` | The caller's own connections eligible for this job (card only) | V; never a third party's connections |
| `POST /jobs/{id}/referral-requests/` `{referrer_id, message}` | Create request | V; `422 not_eligible` (same response whether not connected, not a member, or opted out); `409` duplicate / cap |
| `GET /referrals/requests/?role=requester\|referrer&status=` | My requests, either side | U |
| `GET /referrals/requests/{id}/` | Detail + history | Requester, referrer; job manager from `REFERRED` |
| `POST /referrals/requests/{id}/accept/` · `/decline/` | Respond | Referrer |
| `POST /referrals/requests/{id}/cancel/` | Cancel | Requester |
| `POST /referrals/requests/{id}/refer/` `{endorsement_note}` | Submit referral | Referrer |

### Events

| Method & path | Purpose | Authorization / notes |
|---|---|---|
| `POST /events/{id}/register/` | Register | V. Response `{status: CONFIRMED\|WAITLISTED, waitlist_position?}`; `200` if already registered; `409 registration_closed` |
| `POST /events/{id}/cancel-registration/` | Cancel | Registrant |
| `GET /events/{id}/my-registration/` | Status + check-in QR payload (confirmed only) | Registrant |
| `GET /events/{id}/registrations/?status=` | Attendee management | Event manager |
| `GET /events/{id}/attendees/` | Public attendee list | Per `attendee_visibility` |
| `POST /events/{id}/check-in/` `{token}` | Check in | Event manager. `200 {attendee, checked_in_at}`; `409 already_checked_in` (returns original time); `422` invalid/wrong event/not confirmed/outside window |
| `POST /events/{id}/open-registration/` · `close-registration/` · `cancel/` | Event transitions | Event manager |
| `GET /users/me/event-registrations/` | My events | U |

The server never accepts a `checked_in` flag; check-in state changes only through a verified token.

### Messaging and notifications

| Method & path | Purpose | Authorization / notes |
|---|---|---|
| `GET /conversations/` | Inbox ordered by `last_message_at`, with unread counts | U |
| `POST /conversations/` `{user_id}` | Get-or-create 1:1 | V; must be an accepted connection; blocked → `404` |
| `GET /conversations/{id}/messages/?before=&after=` | History (keyset) | Participant |
| `POST /conversations/{id}/messages/` `{body, client_id}` | Send | Participant; not blocked/restricted; `201` new, `200` replay of the same `client_id`; throttled |
| `POST /conversations/{id}/read/` `{up_to_message_id}` | Mark read (monotonic) | Participant |
| `GET /notifications/?unread=` · `GET /notifications/unread-count/` | List / badge | U |
| `POST /notifications/{id}/read/` · `POST /notifications/read-all/` | Mark read (idempotent) | Recipient |

### Moderation and admin

| Method & path | Purpose | Authorization / notes |
|---|---|---|
| `POST /reports/` `{target_type, target_id, category, description, community_id?}` | File a report | V; `409` duplicate open report; throttled |
| `GET /reports/mine/` | Own reports and status | U |
| `GET /moderation/reports/?status=&category=` | Platform queue | Platform `MODERATOR+` |
| `GET /communities/{id}/reports/` | Community queue | Community `MODERATOR+` |
| `POST /moderation/reports/{id}/claim/` | `OPEN → UNDER_REVIEW` | Moderator in scope |
| `POST /moderation/reports/{id}/resolve/` `{action_type, reason, expires_at?}` | Take action + `ACTION_TAKEN` (atomic) | Moderator in scope; community moderators limited to community-level removal |
| `POST /moderation/reports/{id}/dismiss/` `{note}` | `DISMISSED` | Moderator in scope |
| `POST /moderation/actions/` · `POST /moderation/actions/{id}/revert/` | Action without a report / revert | Platform `MODERATOR+` (suspend, verify: `ADMIN`) |
| `GET /admin/audit-logs/?actor=&action=&target=` | Audit search | Platform `ADMIN` |
| `GET /organizations/{id}/audit-logs/` · `GET /communities/{id}/audit-logs/` | Tenant audit | Tenant `OWNER` |
| `GET /admin/stats/` | Dashboard counts | Platform `ADMIN` |

---

## 9. WebSocket Architecture

**Route**: one authenticated, user-scoped, server-to-client socket: `/ws/stream/` (D4). It carries notifications, new messages for all the user's conversations, and status updates. Per-conversation sockets are not used: the inbox needs events from every conversation, and one socket means one authorization check and one reconnect path.

**Authentication**: the browser cannot set headers on a WebSocket, and the access token must not appear in URLs.
1. Client calls `POST /auth/ws-ticket/` → random ticket stored in Redis (`ws:ticket:{t} → user_id`, TTL 30 s).
2. Client connects to `/ws/stream/?ticket=…`. Middleware does `GETDEL` (single-use), loads the user, rejects suspended users, close code `4401` on failure.
3. `AllowedHostsOriginValidator` enforces origin. Nginx does not log the query string for `/ws/`.

**Authorization**: the consumer joins exactly one group, `user.{user_id}`, derived server-side. Clients cannot subscribe to anything. All fan-out decisions (who receives an event) are made by services at publish time using the same policies as REST.

**Lifecycle**
- Connect → accept → join group → send `hello {server_time, session_expires_at}`.
- Heartbeat: client `ping` every 30 s, server `pong`; server drops silent sockets after 75 s.
- Sessions are capped at 60 minutes (close `4401`); the client fetches a new ticket and reconnects. Suspension or logout publishes `session.revoked` to the group, which closes all sockets immediately.
- Disconnect → leave group.

**Event envelope**: `{event_id, type, occurred_at, data}`.

| Type | Data (minimal) | Client reaction |
|---|---|---|
| `notification.created` | Notification as in REST | Prepend to cache, bump unread count |
| `notification.read` | `ids` or `all` | Sync other tabs/devices |
| `message.created` | Message + `conversation_id` | Append if thread cached; update inbox preview/unread |
| `conversation.read` | `conversation_id`, `up_to_message_id` | Update read receipt |
| `application.updated`, `referral.updated`, `event.updated`, `registration.updated` | `id`, `status` | Invalidate the matching query |

Payloads contain only what the recipient may see; status events carry IDs and the client refetches through authorized REST.

**Delivery, duplicates, reconnect, offline**
- Flow: service writes rows → `on_commit` → Celery `notifications` queue → `channel_layer.group_send`. If the worker or layer fails, nothing is lost: the row exists.
- The channel layer is at-most-once and unordered across reconnects. Clients dedupe by `event_id`/entity ID and treat the socket as a cache-update hint.
- Reconnect: exponential backoff with jitter (1 s → 30 s cap). On every (re)connect the client invalidates unread count, notifications, inbox, and fetches open threads with `?after=<last_message_id>`.
- Offline: no socket means no push; the user sees everything on next load. Email covers important notification types according to preferences. No per-user offline queue in Redis.
- Sending messages is REST-only: validation, throttling, persistence, and idempotency (`client_id`) live in one code path. The sender's optimistic message is reconciled by `client_id`.

**PostgreSQL vs Redis**

| PostgreSQL (durable) | Redis (ephemeral, safe to lose) |
|---|---|
| Messages, conversations, read positions | Channel-layer groups and in-flight events |
| Notifications, deliveries, preferences | Socket tickets (30 s) |
| All state, history, audit | Throttle counters, cache entries |
| Aggregated stats | View counters awaiting flush, Celery broker queue |

Typing indicators and presence (Redis-only) are a could-have.

---

## 10. Celery Architecture

**Configuration**: Redis broker; results disabled (`ignore_result`) unless needed; `acks_late=True`, `reject_on_worker_lost=True`, `worker_prefetch_multiplier=1`; JSON serializer; soft/hard time limits on every task; tasks take IDs, never model instances; request ID propagated in headers. **Exactly one beat instance.** No long ETA/countdown tasks — time-based work is done by sweepers.

**Queues**: `email`, `notifications` (socket push, fan-out; low latency), `default`, `scheduled` (sweepers), `analytics` (low priority). MVP runs one worker consuming all queues; they are separated so they can be split later without code changes.

| Task | Trigger | Queue | Retry | Idempotency | On final failure |
|---|---|---|---|---|---|
| `deliver_notification(id)` | `on_commit` after notification insert | notifications | 3×, short backoff | Push is harmless to repeat (client dedupes) | Log; row still visible via REST |
| `send_notification_email(delivery_id)` | Same, when preference allows | email | 5×, exponential backoff + jitter, on transient SMTP errors | Conditional `UPDATE … SET status='SENT' WHERE status='PENDING'` claims the row before sending | `FAILED`, error tracked |
| `send_transactional_email(kind, user_id, …)` | Register, reset, invitation | email | Same | Token is single-use; duplicate email is harmless | Tracked; user can resend |
| `redispatch_pending_deliveries` | Beat, every 5 min | scheduled | — | Selects `PENDING` older than 5 min with `SKIP LOCKED` | Next run |
| `fanout_opportunity_published(opportunity_id, community_id)` | `on_commit` at publish/approval | notifications | 3× | `bulk_create(ignore_conflicts)` on `dedupe_key`; chunks of 500 | Partial fan-out; logged |
| `expire_opportunities` | Beat, every 5 min | scheduled | — | Conditional bulk update `WHERE status='PUBLISHED' AND deadline < now()` returning IDs, then per-ID side effects | Next run |
| `advance_event_states` | Beat, every minute | scheduled | — | Conditional updates per transition (open, close, complete) | Next run |
| `send_event_reminders` | Beat, every 5 min | scheduled | — | Claims event with `UPDATE … SET reminder_24h_sent_at=now() WHERE … IS NULL`; notification `dedupe_key = reminder:{event}:{kind}` | Next run |
| `expire_referral_requests` | Beat, hourly | scheduled | — | Conditional update on `REQUESTED AND expires_at < now()` | Next run |
| `expire_invitations` / `archive_old_opportunities` | Beat, daily | scheduled | — | Conditional updates | Next run |
| `reindex_organization_opportunities(org_id)` | Org rename | default | 3× | Recomputes from source | Tracked |
| `flush_view_counters` | Beat, every 5 min | analytics | — | `GETDEL` per key then `F()` increment; a crash in between loses a few views (accepted) | Next run |
| `aggregate_daily_stats(date)` | Beat, nightly | analytics | 3× | Upsert on `(opportunity, date)`; recomputed from history tables | Tracked |
| `cleanup_expired_data` | Beat, daily | scheduled | — | Deletes blacklisted tokens, old read notifications (>90 d), nulls audit IPs (>90 d), orphaned uploads | Next run |
| `send_opportunity_digest` (should-have) | Beat, weekly | email | 3× | `DigestRun(user, period)` unique | Skipped for that period |

Rule: an HTTP request never sends email, never pushes to sockets, never fans out, never aggregates.

---

## 11. Search Architecture

**Indexed document** (`Opportunity.search_vector`, `english` config with `unaccent`):

| Weight | Source |
|---|---|
| A | `title` |
| B | Skill names (`skills_text`), organization name |
| C | City, region, employment type / event format |
| D | `description` |

**Indexes**: GIN on `search_vector`; GIN trigram on `title`; trigram on `Skill.name`, `Organization.name`, `Community.name` (autocomplete and entity search); B-tree indexes from §4 for filters and sorts.

**Query**: `websearch_to_tsquery('english', q)` ranked by `ts_rank_cd`. If full-text returns nothing, fall back to trigram similarity on `title` (typo tolerance), threshold 0.3. Autocomplete endpoints use trigram prefix matching, limited to 10.

**Filters** (all SQL, all URL parameters): `q`, `type`, `skill` (repeatable; any-match via `Exists`), `country`, `city`, `work_mode`, `experience_level`, `employment_type`, `community`, `organization`, `deadline_before/after`, `starts_before/after` (events), `posted_within`, `saved=true`, `scope=global|communities|following`.

**Sorting and pagination**

| Sort | Order | Pagination |
|---|---|---|
| `newest` (default without `q`) | `published_at DESC, id` | Keyset cursor |
| `deadline` | `deadline ASC NULLS LAST, id` | Keyset cursor |
| `relevant` (default with `q` or on home feed) | score below | Offset, capped at 500 results |
| `popular` | `popularity_score DESC, id` | Offset, capped at 500 results |

**Deterministic relevance** (authenticated; computed as SQL annotations over the filtered, visible candidate set, restricted to the last 90 days when no `q`):

```text
score = 5 × min(matching HAS skills, 4)
      + 3 × min(matching INTERESTED skills, 4)
      + 3 × [approved in a community the user belongs to]
      + 2 × [same city, or same country when the user has no city]
      + 2 × [work mode equals the user's preference]
      + 1 × [user follows the organization]          -- contributes 0 until follows ship
order: with q → ts_rank_cd DESC, score DESC, published_at DESC, id
       without q → score DESC, published_at DESC, id
```

The user's skill IDs, community IDs, and location are loaded once and passed as literals. The caps stop keyword-stuffed listings from dominating. The response includes `match_reasons` (e.g. `["skill:react", "community:kochi-developers", "work_mode"]`) so every ranking is explainable. No learned signals, no per-user hidden state.

Organizations, communities, and users have separate, simpler search endpoints (trigram on name; users return public cards only).

---

## 12. React Architecture

**Stack**: React + TypeScript (strict) + Vite, React Router (data router, lazy routes), TanStack Query, Redux Toolkit (minimal), React Hook Form + Zod, Tailwind CSS with accessible headless primitives, Vitest + Testing Library + MSW, Playwright.

**State ownership**

| Kind | Where | Examples |
|---|---|---|
| Server state | TanStack Query | Opportunities, applications, notifications, messages, memberships |
| URL state | Router search params via typed hooks | Filters, sort, search query, tab, pagination cursor |
| Local UI state | Component `useState`/`useReducer` | Modal open, form drafts, pipeline drag state |
| Global client state | Redux Toolkit — three small slices | `auth` (access token in memory, session status), `realtime` (socket status), `ui` (toasts) |

Server data is never copied into Redux.

**Routes**

```text
PublicLayout     /login /register /verify-email /forgot-password /reset-password
                 /invitations/:token
AppLayout (auth) /                         home feed
                 /opportunities            search (?q&type&skill&work_mode&sort…)
                 /opportunities/new        /opportunities/:id        /opportunities/:id/edit
                 /opportunities/:id/applications      (pipeline, manager)
                 /opportunities/:id/attendees         /opportunities/:id/check-in
                 /applications   /applications/:id
                 /referrals      (tabs: sent / received)
                 /events/mine    /saved
                 /communities    /communities/:slug   (tabs: feed, members, about)
                 /communities/:slug/manage            (queue, members, reports, settings)
                 /organizations/:slug                 /organizations/:slug/manage
                 /connections    /messages   /messages/:conversationId
                 /notifications  /users/:id  /settings/*
AdminLayout      /admin/reports  /admin/users  /admin/organizations  /admin/audit  /admin/stats
```

Guards: `RequireAuth`, `RequireVerified`, `RequirePlatformRole`; tenant-management routes check the membership role from `/users/me/` and still handle a server `403`.

**Structure** — feature folders as in CLAUDE.md; each `features/<name>/` contains `api/` (query keys, query/mutation hooks), `components/`, `routes/`, `schemas.ts`, `types.ts`. Shared: `services/http.ts`, `services/realtime.ts`, `components/` (design-system pieces), `hooks/`, `app/` (providers, router, store).

**Authentication flow**
- On load, call `/auth/refresh/` (cookie) → access token in memory → `/users/me/`. A splash state covers this.
- The HTTP client attaches the token; on `401` it runs a **single-flight** refresh and retries once; a failed refresh clears the session and redirects to login with a return URL.
- Logout clears the query cache and closes the socket.

**API layer**: one typed fetch wrapper; types generated from the OpenAPI schema; a query-key factory per feature; mutations invalidate by key or apply optimistic updates (save, mark-read, send message) with rollback.

**Forms**: React Hook Form + Zod schemas; server `errors{}` are mapped onto fields; the opportunity form is one component with a type-specific section; drafts autosave through `PATCH`.

**Errors**: normalized `ApiError {status, code, detail, fieldErrors, requestId}`; route-level error boundaries with retry; `404`/`403` pages; toasts for mutation failures; `409 stale_state` refetches and tells the user the item changed.

**Realtime**: a `RealtimeProvider` owns the single socket (ticket → connect → backoff reconnect), dedupes by `event_id`, and translates events into `setQueryData`/`invalidateQueries`. Components never touch the socket. A banner shows degraded state; the app works fully without it.

**Permission-aware UI**: `<Can>`/`useCan` read the `viewer` block on resources and the membership roles from `/users/me/`. Controls are hidden or disabled with a reason; the server remains the authority.

**Reusable components**: `OpportunityCard`, `FilterBar`, `StatusBadge`, `DataList` (loading / empty / error / paginated), `ConfirmDialog`, `FileUpload`, `SkillPicker`, `EntityAvatar`, `Timeline` (status history), `PipelineBoard`, `QRCode`/`QRScanner`.

Every screen implements loading, empty, success, and error states.

---

## 13. MVP Scope

### Must have
- Auth: register, email verification, login, refresh, logout, password reset.
- Profile: basics, skills/interests, location, work-mode preference, profile visibility, avatar.
- Organizations: create, invitations, roles, last-owner rule, manual verification flag.
- Communities: create, join policies, membership approval, roles, rules text.
- Opportunity core with **Job and Event** types; draft/publish/close/expire/archive.
- Multi-community distribution with per-community approval and featuring.
- Feed and search: full-text, filters in the URL, newest/deadline/relevant sorts, saved.
- Job applications with resume upload and the recruiter pipeline.
- Connections, blocks, and the referral workflow.
- Events: registration, capacity, waitlist, QR check-in, reminders.
- Notifications: in-app, WebSocket, email for key types; per-category preferences.
- One-to-one messaging with unread state.
- Reports, moderation actions (hide/remove, warn, suspend, restrict posting), community and platform queues.
- Audit log from day one; admin stats from simple aggregates.
- Rate limiting, Docker Compose environment, CI, health checks, structured logs.

### Should have (shortly after MVP)
- Project and Mentorship types (new detail tables + a join/request workflow reusing the application pattern).
- Organization follows and the "following" feed.
- View tracking, `popular` sort, opportunity/job/event/referral funnels.
- Weekly digest email.
- External application method; reopen a closed opportunity.
- Per-event check-in staff; account deactivation/anonymization; recruiter notes on applications.
- `Idempotency-Key` support on create endpoints; Prometheus metrics.

### Could have (later)
- Typing indicators, presence, message attachments, group conversations.
- Referral-offer posts; domain-based organization verification; reputation.
- Saved searches and alerts; calendar (`.ics`) export; direct-to-storage uploads.
- Reporting of messages (with a privacy policy).

### Do not build yet
- Subscriptions, billing, premium tiers, featured-placement payments.
- Community discussions/resources; project workspace (tasks, files, milestones).
- Screening questionnaires, interview scheduling, offer management (ATS territory).
- Ticketing/payments for events; a calendar engine for mentorship.
- Elasticsearch/OpenSearch, Kafka, microservices, GraphQL, Kubernetes, schema-per-tenant, row-level security.
- Any AI/ML ranking.

---

## 14. Implementation Phases

Each phase is a vertical slice (backend + frontend + tests) and ends deployable in Docker Compose. "Done" for every phase also requires: migrations included, permissions tested, loading/empty/error states present, lint + type checks + tests green, query counts checked on list endpoints.

**Phase 0 — Foundation**
- Features: none user-visible; a running skeleton.
- Backend: project + split settings (env-driven), custom `User` model, `common` (base model, error envelope, pagination, request-ID middleware, state-machine helper, throttles, storage abstraction), `audit` app, health endpoints, Celery app + beat, Channels ASGI app with an authenticated echo-less stream stub, OpenAPI schema.
- Frontend: Vite app, router, layouts, query client, store, HTTP client, error boundary, design tokens and base components.
- Database: extensions, `users_user`, `audit_auditlog`.
- APIs: `/healthz`, `/readyz`, `/api/v1/schema/`.
- Tests: pytest + factories wired; one test per layer; Vitest wired; CI running lint, types, tests.
- Depends on: nothing.
- Done: `docker compose up` serves the SPA and API through Nginx; worker executes a ping task; health checks pass; CI green.

**Phase 1 — Authentication, Users, Profiles**
- Features: register, verify, login, refresh, logout, reset; profile editing; skills; avatar; privacy.
- Backend: token rotation with reuse detection, auth throttles, transactional email via Celery, profile privacy policy, image validation and re-encoding.
- Frontend: auth pages, session bootstrap, single-flight refresh, settings, profile view/edit, `SkillPicker`.
- Database: profile, experience, education, skill, user-skill, block.
- APIs: Auth and users table (§8).
- Tests: auth flows, token reuse, enumeration resistance, privacy matrix, upload validation.
- Depends on: 0.
- Done: a new user can register, verify by email (Mailpit), log in across reloads, and edit a profile whose visibility is enforced.

**Phase 2 — Organizations and Communities**
- Features: create tenants; invitations; roles; join/approve/leave; rules.
- Backend: both membership state machines, last-owner rule, invitation tokens, membership policies, audit on every change.
- Frontend: org and community pages, management screens, invitation acceptance, membership-aware navigation.
- Database: organization, member, invitation; community, member, invitation, rule.
- APIs: Organizations and Communities tables (minus distribution).
- Tests: permission matrix per role × action, transition tests, concurrent last-owner demotion, invite token reuse.
- Depends on: 1.
- Done: a user belongs to several orgs and communities with different roles, and every forbidden action is rejected server-side.

**Phase 3 — Opportunity Core, Jobs, Distribution, Search**
- Features: create/edit/publish/close job opportunities; distribute to communities with approval; feed, search, filters, relevance; save.
- Backend: `Opportunity` + `JobDetail`, lifecycle machine, visibility queryset, distribution workflow, search vector + reindex, relevance annotations, expiration sweeper.
- Frontend: opportunity form, detail, feed/search with URL filters, community review queue, saved list, "my opportunities".
- Database: opportunity, skill link, distribution, saved, job detail; search and filter indexes.
- APIs: Opportunities table; community submissions endpoints.
- Tests: lifecycle transitions, visibility matrix (visibility × membership × status × moderation), search/filter correctness, relevance ordering, `assertNumQueries` on feed, sweeper idempotency.
- Depends on: 2.
- Done: the PRD scenario works up to "candidate discovers it through skill/community match".

**Phase 4 — Notifications and WebSocket infrastructure**
- Features: notification centre, unread badge, live delivery, email delivery, preferences.
- Backend: `notify()` service, deliveries, preference resolution, ticket endpoint, stream consumer, push and email tasks, redispatch sweeper; wire Phase 2–3 events (invitations, join requests, submission decisions, expiry).
- Frontend: `RealtimeProvider`, notification list and dropdown, preferences screen, reconnect handling.
- Database: notification, delivery, preference.
- APIs: Notifications table, `/auth/ws-ticket/`.
- Tests: consumer auth (bad/used/expired ticket, origin), group isolation, dedupe, preference matrix, redispatch after simulated broker failure.
- Depends on: 3.
- Done: an action by one user produces a live notification and an email for another, and survives a socket drop and a worker restart.

**Phase 5 — Applications**
- Features: apply with resume, my applications, recruiter pipeline, withdraw.
- Backend: application machine, history, private resume storage with signed URLs, notifications, audit.
- Frontend: apply flow, application tracker with timeline, pipeline board with stale-state handling.
- Database: application, status history.
- APIs: Jobs and applications table.
- Tests: full transition matrix, duplicate-apply concurrency, cross-org access (IDOR) tests, resume access control.
- Depends on: 3, 4.
- Done: a candidate applies and a recruiter moves them to `HIRED` with notifications at each step.

**Phase 6 — Connections and Referrals**
- Features: connect, block, eligible-referrer selection, referral request lifecycle, outcome tracking.
- Backend: canonical-pair connections, eligibility selector, referral machine, application ↔ referral sync, expiry sweeper.
- Frontend: connections screen, referral request dialog, sent/received referrals with timelines, referral badge in the pipeline.
- Database: connection, referral request, history.
- APIs: Connections and referrals table.
- Tests: eligibility matrix, privacy (no third-party graph access, uniform errors), transition matrix, accept-vs-cancel race, sync with application outcomes.
- Depends on: 5.
- Done: the full PRD §36 scenario runs end to end.

**Phase 7 — Events**
- Features: event opportunities, registration, waitlist, cancellation, QR check-in, attendee management, reminders.
- Backend: `EventDetail`, event and registration machines, capacity locking, token issue/verify, state and reminder sweepers.
- Frontend: event form section, event detail with registration state, my events with QR, attendee list, scanner screen.
- Database: event detail, registration.
- APIs: Events table.
- Tests: capacity under concurrency (N parallel registrations for 1 seat), waitlist promotion order, check-in replay/forgery/wrong-event, reminder idempotency, time-zone handling.
- Depends on: 3, 4.
- Done: an event fills, waitlists, promotes on cancellation, and checks in each attendee exactly once.

**Phase 8 — Messaging**
- Features: 1:1 conversations, inbox, unread, live delivery.
- Backend: canonical-pair conversations, idempotent send, read positions, connection/block policy, throttles.
- Frontend: inbox, thread with optimistic send and reconciliation, reconnect catch-up.
- Database: conversation, participant, message.
- APIs: Messaging table.
- Tests: participant-only access, duplicate `client_id`, ordering and catch-up, block enforcement.
- Depends on: 4, 6.
- Done: two users chat in real time; nothing is lost or duplicated across a disconnect.

**Phase 9 — Moderation and Admin**
- Features: reporting, community and platform queues, actions, verification, suspension, audit viewer, stats.
- Backend: report machine, action application and revert, restrictions enforced in policies, session revocation on suspend, audit read APIs.
- Frontend: report dialog, moderation queues, action dialogs, admin screens; Django admin for raw entity management.
- Database: report, moderation action, user restriction.
- APIs: Moderation and admin table.
- Tests: scope tests (community moderator cannot act platform-wide), every action writes audit, hidden content disappears from feed/search/detail, suspension blocks REST and socket.
- Depends on: 3–8.
- Done: a reported opportunity can be reviewed and hidden; the audit trail shows who did what.

**Phase 10 — Analytics** (should-have, first post-MVP)
- View counters, stats tables, nightly aggregation, funnels per opportunity/org/community, `popular` sort.
- Tests: aggregation idempotency, funnel numbers vs fixtures.
- Depends on: 5–7.

**Phase 11 — Production Hardening**
- Security review against §16, load test of feed/search/registration, slow-query review, metrics, backups and restore test, production compose/Nginx/TLS, CI/CD, audit immutability trigger, documentation.
- Done: checklist signed off; restore drill passes.

**After MVP**: Projects and Mentorship, follows, digests, remaining should-haves.

---

## 15. Testing Strategy

**Tooling**: pytest, pytest-django, factory_boy, `channels.testing`, Celery eager mode for unit tests plus a small set against a real worker; Vitest, Testing Library, MSW; Playwright.

| Level | What it covers |
|---|---|
| Unit | Policies (pure functions), state-machine tables, relevance scoring, token generation/verification, serializers |
| Service / integration | Each service against real PostgreSQL: transitions, side effects (history, audit, notification rows), `on_commit` behaviour |
| API | Status codes, error envelope, pagination, filters, throttles; every endpoint tested as anonymous, unrelated user, each role, and owner |
| Permission matrix | Parametrized role × action tables per domain; cross-tenant access always asserted `404`/`403` |
| State machine | Generated from the transition table: every valid edge passes, every other pair is rejected |
| Database constraints | Direct ORM writes that bypass services must fail (unique, check, capacity) |
| Concurrency | Threaded tests on real PostgreSQL for the races in §17 |
| Query count | `assertNumQueries` on feed, search, pipeline, inbox, notification list |
| WebSocket | Ticket auth, origin, group isolation, revoke, event shape |
| Tasks | Idempotency: run each task twice and assert a single effect |
| Frontend unit/component | Forms and validation, permission-aware rendering, filter ↔ URL sync, list states |
| Frontend integration | Feature flows against MSW: auth refresh, apply, pipeline stale state, realtime cache updates |
| End-to-end (Playwright, full stack) | The eleven critical flows in CLAUDE.md, kept few and stable |

**Highest-risk flows — strongest coverage**

1. Event capacity, waitlist promotion, and check-in under concurrency.
2. Tenant isolation: applications, resumes, org/community management, referral visibility.
3. Referral eligibility and privacy (no graph leakage).
4. Application and referral transition matrices, including the cross-machine sync.
5. Opportunity visibility across visibility × membership × status × moderation.
6. Token lifecycle: refresh rotation/reuse, socket tickets, invitation and check-in tokens.
7. Last-owner invariant.
8. Notification durability (no loss when broker or socket fails; no duplicates on retry).

---

## 16. Security Review

| Area | Risk | Mitigation |
|---|---|---|
| Authentication | Credential stuffing, token theft, enumeration | Argon2 hashing; login throttled per IP + email; access token 10 min, in memory only; refresh in `HttpOnly; Secure; SameSite=Strict` cookie scoped to `/api/v1/auth/`, rotated with reuse detection; uniform responses on register/reset; password change revokes all sessions |
| Authorization | Missing checks on new endpoints | Deny-by-default base view; policy per action; services re-validate; permission matrix tests required for every endpoint |
| Multi-tenancy | Cross-tenant reads/writes | Scoped querysets as the only way to load objects; tenant derived from the object, never from a client-supplied ID alone; nested routes verify child ∈ parent |
| IDOR / BOLA | Guessing IDs | UUIDs; `404` for invisible objects; object-level policy on every detail and action route; automated cross-user tests |
| File uploads | Malicious files, PII exposure, storage abuse | Size limits in Nginx and Django; allow-list by sniffed content type (not client MIME or extension); images re-encoded (strips metadata); random storage keys; resumes in a private bucket behind short-lived signed URLs served as attachments; per-user upload throttle |
| WebSockets | Token leakage, hijacking, over-subscription | Single-use 30 s ticket; origin validation; server-chosen group only; no client subscriptions; session cap and revocation; minimal payloads |
| Rate limiting | Abuse, scraping, spam | Redis-backed scoped throttles: auth, search, connection requests, referral requests, messages, reports, uploads; Nginx connection limits |
| Messaging | Spam, harassment | Connections-only; block enforcement both ways; message length limit; throttles; messaging restriction as a moderation action |
| Referral privacy | Mapping who works where / who knows whom | Only the caller's own connections are ever returned; membership must be visible to connections; uniform `not_eligible` error; recruiters see a referral only from `REFERRED`; decline carries no reason |
| Community membership | Reading private communities, self-approval | Private community content members-only; approvals require `MODERATOR+`; banned users cannot rejoin; role changes cannot be self-applied |
| Organization access | Privilege escalation, hijack through invitations | Role-bounded role changes; last-owner rule; invitation bound to a verified email, hashed single-use token, expiry |
| Admin actions | Abuse of power, no accountability | Separate endpoints requiring platform role; reason mandatory; every action audited; suspension and verification restricted to `ADMIN`; Django admin restricted to staff over HTTPS |
| Audit logs | Tampering, PII accumulation | Append-only in code and by DB trigger; no secrets or message bodies in metadata; IP nulled after 90 days; read access scoped |
| Sensitive information | Leaks through APIs, logs, analytics | Explicit serializer field lists (never `__all__`); separate public/private serializers; log scrubbing of tokens, passwords, emails; analytics store counts, not identities |
| CSRF / CORS | Cross-site requests | Bearer header for the API (not cookie-authenticated); the cookie-authenticated refresh/logout endpoints require `SameSite=Strict`, an `Origin` check, and a custom header; CORS allow-list of the SPA origin only, credentials limited to auth routes |
| XSS | Stored script in descriptions/messages | React escaping; no `dangerouslySetInnerHTML`; restricted Markdown renderer without raw HTML; strict CSP; URL fields validated to `http(s)` |
| SQL injection | Unsafe queries | ORM only; full-text input passed as parameters to `websearch_to_tsquery`; sort/filter fields from an allow-list |
| Race conditions | Double actions, over-capacity | Transactions, row locks, unique/check constraints, conditional updates (§17) |
| Secrets and transport | Leaked credentials | Environment variables only; `.env` git-ignored with a committed `.env.example`; HSTS, secure cookies, `X-Content-Type-Options`, `Referrer-Policy`, frame denial in production |

---

## 17. Database and Transaction Design

| Operation | Race | Prevention |
|---|---|---|
| Apply to job | Double submit; two tabs | Unique `(opportunity, applicant)`; insert in a transaction, catch `IntegrityError`, return the existing row. Status/deadline checked in the same transaction. A request landing milliseconds after close is accepted as benign (no lock on the job row, to avoid contention on popular jobs). |
| Application transition | Two recruiters move the same application | `SELECT … FOR UPDATE` on the application; transition table; `expected_status`; history + referral sync + audit in the same transaction |
| Event registration | N users, 1 seat | Lock the `EventDetail` row (`FOR UPDATE`); compare `confirmed_count` to `capacity`; insert `CONFIRMED` (increment) or `WAITLISTED`; unique `(event, user)`; `CHECK (confirmed_count <= capacity)` as a backstop |
| Cancellation + promotion | Cancel and register interleave; double promotion | Same event row lock; decrement, select the oldest `WAITLISTED` row, promote, increment — one transaction |
| Capacity change | Shrink below confirmed; grow while registering | Under the event lock; reject shrink below `confirmed_count`; promote up to the new capacity |
| Check-in | Same QR scanned twice / by two staff | `UPDATE … SET checked_in_at = now() WHERE id = ? AND checked_in_at IS NULL AND status = 'CONFIRMED'`; zero rows → `409` |
| Referral create | Exceed per-job cap; duplicate request | Advisory transaction lock on `(requester, opportunity)`; unique `(opportunity, requester, referrer)` |
| Referral accept / decline / cancel / expire | Concurrent opposing actions | Row lock; first transition wins; the sweeper uses a conditional update |
| Referral ↔ application sync | Application created while referral becomes `REFERRED` | Both paths lock the referral row before linking; link is set once |
| Organization role change / removal / leave | Two owners demote each other → zero owners | Lock the `Organization` row first, then count active owners |
| Organization invitation accept | Token used twice | Conditional update `WHERE status = 'PENDING'`; unique `(organization, user)` |
| Community join / approve | Double join; approve vs reject | Unique `(community, user)`; row lock on transitions; same last-owner pattern |
| Connection request | A→B and B→A simultaneously | Canonical pair `(user_low, user_high)` with a unique constraint |
| Conversation create | Two creates for the same pair | Same canonical-pair unique constraint; get-or-create with `IntegrityError` retry |
| Message send | Client retry after timeout | Unique `(conversation, sender, client_id)`; conversation preview updated in the same transaction |
| Publish opportunity | Double publish; publish vs edit | Row lock; state check; distribution rows unique `(opportunity, community)` |
| Expire vs manual close | Sweeper and user act together | Conditional bulk update on `status = 'PUBLISHED'` |
| Report resolve | Two moderators act | Row lock on the report; action + status + audit in one transaction |
| Refresh token rotation | Two tabs refresh simultaneously | Client single-flight; server allows a short grace window for the immediately previous token before treating reuse as theft |
| Counters | Lost updates | `F()` expressions or updates under an existing lock only |

Rules: default `READ COMMITTED`; locks are always taken in the order tenant → parent → child to avoid deadlocks; no network I/O inside a transaction; all external effects go through `on_commit`.

---

## 18. Infrastructure Plan

**Docker Compose services**

| Service | Role | Depends on |
|---|---|---|
| `postgres` | PostgreSQL 17, named volume, health check | — |
| `redis` | Redis 7 (cache, broker, channel layer on separate DBs) | — |
| `backend` | Django ASGI: HTTP API (dev: one process also serves `/ws/`) | postgres, redis (healthy) |
| `ws` (production profile) | Same image, serves `/ws/` only | postgres, redis |
| `worker` | Celery worker, same image | postgres, redis |
| `beat` | Celery beat, single instance | redis |
| `frontend` | Vite dev server (dev); in production a build stage whose output Nginx serves | backend |
| `nginx` | Single origin: `/` SPA, `/api/` backend, `/ws/` websocket upgrade, body-size limits, request ID | backend, frontend |
| `minio` | S3-compatible object storage (dev) | — |
| `mailpit` | Captures outgoing email (dev) | — |

A one-shot `migrate` step runs before `backend` starts. Development mounts source with hot reload; everything is reached through Nginx on one origin so cookie, CORS, and WebSocket behaviour match production.

**Object storage**: Django storage abstraction (`django-storages`, S3 API). Two buckets/prefixes: `public` (avatars, logos, event images) and `private` (resumes; signed URLs only). MinIO locally, any S3-compatible service in production.

**Environments**

| | Development | Production |
|---|---|---|
| Config | `.env` from `.env.example` | Environment/secret store; `DEBUG` off |
| App servers | `runserver` (ASGI) | gunicorn + uvicorn workers for the API; separate `ws` process |
| Static/SPA | Vite dev server | Built assets served by Nginx |
| TLS | none (localhost) | Terminated at Nginx or a managed load balancer |
| Email | Mailpit | SMTP provider |
| Storage | MinIO | S3-compatible bucket |
| Data | Local volumes, seed command | Managed PostgreSQL/Redis preferred; daily backups, tested restore |

CI (GitHub Actions): backend lint (ruff), types (mypy), tests against PostgreSQL + Redis services, migration check; frontend lint, type check, tests, build; Playwright on the composed stack for the main branch.

---

## 19. Observability Plan

| Concern | MVP approach |
|---|---|
| Structured logging | JSON logs to stdout (structlog) with `request_id`, `user_id`, route, status, duration; secrets scrubbed |
| Request IDs | Nginx generates/forwards `X-Request-ID`; middleware binds it to logs, returns it in responses and error bodies, propagates it into Celery task headers and audit rows |
| Error tracking | Sentry SDK in Django, Celery, and React, enabled only when a DSN is configured |
| Celery monitoring | Task start/success/failure/retry logs with task and request IDs; failures to Sentry; beat heartbeat key in Redis checked by readiness; Flower in the dev profile |
| Database queries | Debug toolbar in dev; query-count tests; PostgreSQL `log_min_duration_statement` (200 ms) and `pg_stat_statements` |
| WebSocket monitoring | Connect/disconnect/reject logs with close codes; active-connection gauge in Redis |
| Audit logs | Domain-level record (§4), separate from application logs |
| Health checks | `/healthz` (process alive), `/readyz` (database, Redis, migrations applied); Compose health checks use them |
| Metrics | Phase 11: Prometheus endpoint (request latency, task counts/latency, queue depth, socket gauge). No Grafana/ELK stack in MVP. |

---

## 20. Major Technical Risks

| Risk | Mitigation |
|---|---|
| **Scope.** Even the reduced MVP is ten phases. | Strict vertical slices; D1 cut; Phase 10 is explicitly post-MVP; no feature starts before the previous phase meets its "done". |
| **Authorization bugs** across two overlapping tenant types. | One policy module per app, scoped querysets, mandatory permission-matrix tests. |
| **Relevance query cost** as data grows. | Bounded candidate set, capped depth, indexes on join tables; measured in Phase 11; fallback is a precomputed per-user candidate table (not built now). |
| **Concurrency correctness** in events and state machines. | Row locks + constraints + real-PostgreSQL concurrency tests. |
| **Cross-machine coupling** (application ↔ referral). | Single writer, explicit service call, shared transaction, dedicated tests. |
| **Notification volume** from community fan-out. | Opt-in, chunked, deduplicated; digest later. |
| **Redis as broker** (at-least-once, redelivery). | Idempotent tasks, no long ETAs, sweepers; RabbitMQ only if a real need appears. |
| **Search vector drift** from denormalized fields. | Single `reindex()` entry point, org-rename task, a management command to rebuild all. |
| **Generic targets without FKs** (audit, notifications). | Limited to those two tables; target existence handled gracefully at read time. |

---

## Recommended First Implementation Task

**Phase 0, task 1 — "Project skeleton: repository, Docker Compose stack, Django + React scaffolds, custom User model, health checks, and tooling."**

Exact scope, after approval:

1. `git init`, `.gitignore`, `.env.example`, `README.md` with run instructions; commit this plan as `docs/architecture/implementation-plan.md`.
2. `docker-compose.yml` with `postgres`, `redis`, `backend`, `worker`, `beat`, `frontend`, `nginx`, `minio`, `mailpit`, with health checks and dependency ordering.
3. `backend/`: Django project `config` (settings `base/dev/test/prod` from environment variables, ASGI, Celery app), apps `common`, `users`, `audit`.
   - `users.User`: custom model (UUID primary key, email login, `platform_role`, `email_verified_at`) — **in the first migration**.
   - `common`: base model, error envelope + exception handler, cursor pagination, request-ID middleware, `pg_trgm`/`unaccent` migration, state-machine helper with unit tests.
   - `audit`: `AuditLog` model and `record()` service.
   - `/healthz`, `/readyz`, OpenAPI schema endpoint, a Celery ping task.
4. `frontend/`: Vite + React + TypeScript (strict), router with public/app layouts, TanStack Query provider, minimal Redux store, typed HTTP client with the error model, an error boundary, a placeholder home page that calls `/readyz`.
5. Tooling: ruff, mypy, pytest (+ pytest-django, factory_boy); ESLint, Prettier, Vitest; a GitHub Actions workflow running all of them.

Explicitly **not** in this task: authentication endpoints, profiles, or any domain model beyond `User` and `AuditLog`.

## Verification (for that first task)

- `docker compose up --build` brings every service to healthy.
- `curl http://localhost/healthz` and `/readyz` return `200` through Nginx; `/readyz` fails when PostgreSQL or Redis is stopped.
- The SPA loads at `http://localhost/` and shows the readiness result.
- `docker compose exec backend python manage.py migrate --check` reports no pending migrations; `showmigrations` shows `users.0001` creating the custom user.
- `docker compose exec backend celery -A config call common.ping` is executed by the worker (visible in worker logs with a request/task ID).
- `pytest`, `ruff check`, `mypy`, `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` all pass locally and in CI.
- An induced API error returns the standard error envelope including `request_id`, and the same ID appears in the backend log line.
