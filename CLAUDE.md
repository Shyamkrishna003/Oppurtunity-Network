# CLAUDE.md — Opportunity Network

## Project Purpose
Opportunity Network is a multi-tenant professional opportunity platform where people, organizations, and communities publish, discover, distribute, and act on jobs, events, referrals, projects, mentorships, gigs, competitions, and similar opportunities.

The core product abstraction is an **Opportunity**, not a social post. The product must not become a generic LinkedIn clone.

## Product Principles
- Opportunity-first architecture.
- Outcome over vanity engagement: applications, referrals, hires, registrations, attendance, joins, completion.
- No AI dependency. Discovery/ranking uses explicit skills, interests, location, communities, opportunity type, experience, and preferences.
- Trust through verification, moderation, reporting, privacy, and audit logs.
- Complexity must come from real workflows, not artificial feature inflation.

## Target Stack
Frontend: React, TypeScript, Vite, React Router, Redux Toolkit only where global client state is justified, TanStack Query/server-state patterns where useful.
Backend: Python, Django, Django REST Framework, Django Channels, Celery.
Data/infra: PostgreSQL, Redis, Docker/Docker Compose, Nginx, object-storage abstraction.

## High-Level Architecture
```text
React SPA
   | HTTPS / WebSocket
   v
Nginx / Reverse Proxy
   +----------------------+
   |                      |
   v                      v
Django REST API      Django Channels
   |                      |
   +----------+-----------+
              |
      Application Services
              |
     +--------+--------+
     |        |        |
 PostgreSQL Redis    Celery
                       |
                Background Jobs
```

PostgreSQL is the source of truth. Redis is for caching, rate limiting, Celery infrastructure, short-lived state, and appropriate real-time infrastructure—not primary persistence.

## Suggested Backend Domains
```text
backend/
├── config/
├── users/
├── organizations/
├── communities/
├── opportunities/
├── jobs/
├── events/
├── referrals/
├── applications/
├── connections/
├── messaging/
├── notifications/
├── moderation/
├── subscriptions/
├── analytics/
├── audit/
└── common/
```

Avoid one giant `core` app.

## Core Entities
User, Organization, Community, CommunityMembership, Opportunity, OpportunityAudience, OpportunityCommunity, Job, Event, Project, Mentorship, ReferralOpportunity, Application, EventRegistration, ReferralRequest, Connection, Conversation, Message, Notification, Report, ModerationAction, Subscription, AuditLog.

Common Opportunity fields:
- id, creator, organization, type, title, description
- status, visibility
- location and remote/hybrid/on-site mode
- required skills
- deadline
- created_at, updated_at, published_at

Use specialization/inheritance/one-to-one deliberately rather than one huge table with many unrelated nullable fields.

## Important State Machines
Opportunity:
`DRAFT -> PUBLISHED -> CLOSED/EXPIRED -> ARCHIVED`

Job application:
`APPLIED -> SCREENING -> SHORTLISTED -> INTERVIEW -> OFFER -> HIRED`
or `REJECTED`; users may withdraw where allowed.

Referral:
`REQUESTED -> ACCEPTED/DECLINED -> REFERRED -> APPLICATION_SUBMITTED -> INTERVIEW -> OFFER -> JOINED`

Event:
`DRAFT -> PUBLISHED -> REGISTRATION_OPEN -> REGISTRATION_CLOSED -> COMPLETED/CANCELLED`

Invalid state transitions must be rejected server-side.

## Authorization and Multi-Tenancy
Roles may include User, Recruiter, Organization Admin, Community Admin, Event Organizer, Moderator, Platform Admin.

Every protected mutation must verify authentication, ownership/membership, role permissions, resource state, and object-level access. Never rely on frontend checks for security.

Organizations and communities are logical tenants. Users may belong to multiple organizations/communities; do not assume a single `user.organization`.

## API Rules
Use RESTful APIs, pagination, filtering, predictable errors, proper status codes, transactions for multi-step mutations, and idempotency where duplicate requests are possible.

Example:
```text
GET  /api/opportunities/
POST /api/opportunities/
GET  /api/opportunities/{id}/
PATCH /api/opportunities/{id}/
POST /api/opportunities/{id}/publish/
POST /api/opportunities/{id}/close/

POST /api/jobs/{id}/apply/
POST /api/referrals/{id}/request/
POST /api/referrals/requests/{id}/accept/
POST /api/events/{id}/register/
POST /api/events/{id}/check-in/
```

Use explicit action endpoints for true state transitions instead of arbitrary PATCH operations.

## Database
Use PostgreSQL with foreign keys, unique/check constraints, appropriate indexes, and migrations for every schema change.

Common indexes should cover actual query patterns such as opportunity status/type/deadline, organization, creator, community, published_at, application user/opportunity, event/opportunity, and referral requester/referrer.

Avoid N+1 queries; use `select_related`, `prefetch_related`, pagination, and database aggregation.

## Search
Initial discovery is deterministic. Support keyword, type, skill, location, work mode, experience, community, organization, date/deadline. PostgreSQL full-text/trigram search is sufficient initially.

Never fetch the entire dataset and filter in Python.

A deterministic relevance example:
- +5 matching skill
- +3 matching interest
- +3 matching community
- +2 matching location
- +2 matching work mode
- +1 followed organization

## Notifications and Async Jobs
Notifications: in-app, WebSocket, email.

Examples:
- referral requested/accepted
- application status changed
- event registration/reminder
- community invitation
- followed-community opportunity
- new message

Celery should handle email, reminders, opportunity expiration, digests, analytics aggregation, cleanup, and other slow/retryable work.

Background jobs must be idempotent, retry-safe, and observable.

## WebSockets
Use Django Channels for notifications, messaging, and selected live status updates.

Suggested routes:
```text
/ws/notifications/
/ws/conversations/{conversation_id}/
```

Handle reconnects, expired authentication, duplicate events, cleanup, and authorization. Persist messages in PostgreSQL.

## Referral Rules
Referrals are a core differentiator.
1. User discovers an opportunity.
2. User explicitly selects an eligible connection.
3. User sends a referral request.
4. Recipient accepts/declines.
5. If accepted, referral is submitted.
6. Outcome is tracked.

Never expose a complete connection graph or create a referral silently.

## Events
Support event page, organizer, date/time, venue/online URL, capacity, registration, waitlist, cancellation, attendee visibility, QR check-in, attendance, reminders.

Check-in tokens must be server-verifiable; never trust a client boolean such as `checked_in=true`.

## Communities
Communities contain members, admins, opportunities, events, discussions/resources, and rules.

Admins can approve members, moderate/feature opportunities, create events, manage rules, and view analytics.

One opportunity may be distributed to multiple communities.

## Moderation
Reportable resources: users, organizations, communities, opportunities, and messages where policy allows.

Report states:
`OPEN -> UNDER_REVIEW -> ACTION_TAKEN/DISMISSED`

Actions can include hide/remove, warn, suspend, restrict posting, and verification. Every moderation action should create an audit record.

## Audit Logging
Audit security-sensitive actions including login/security events, role changes, membership changes, publishing/deletion, application/referral transitions, moderation, subscription changes, and admin actions.

Store actor, action, resource, timestamp, and relevant metadata. Avoid unnecessary personal data.

## Security
Implement secure Django password handling, CSRF where applicable, restrictive CORS, rate limiting, input validation, object-level authorization, secure headers, file validation/size limits, and secret management through environment variables.

Never commit passwords, tokens, API keys, database credentials, or production secrets.

## File Uploads
Possible files: profile images, logos, event posters, job/project attachments. Use a storage abstraction for local/S3-compatible storage.

Validate MIME type, extension, size, filename, and ownership. Never trust client-provided MIME type or filename alone.

## Frontend Structure
```text
src/
├── app/
├── routes/
├── components/
├── layouts/
├── features/
│   ├── auth/
│   ├── opportunities/
│   ├── jobs/
│   ├── events/
│   ├── referrals/
│   ├── communities/
│   ├── organizations/
│   ├── messaging/
│   └── notifications/
├── services/
├── hooks/
├── store/
├── types/
├── utils/
└── styles/
```

Prefer feature-based organization. Keep local UI state local, server data in server-state mechanisms, and use Redux only for genuinely shared client state.

## UX
Important screens:
- Home/opportunity feed
- Search
- Opportunity details
- Create opportunity
- My applications
- My referrals
- Communities
- Community details
- Events
- Organization page
- Messages
- Notifications
- Profile
- Admin dashboard

Make filters shareable through URL parameters, e.g. `/opportunities?type=job&remote=true&skill=react`.

Always implement useful loading, empty, success, and error states.

## Testing
Backend: unit, API, permission, state-transition, integration, and constraint tests.
Frontend: component, hook where useful, API integration, and critical user-flow tests.

Critical flows:
1. Auth
2. Create/publish opportunity
3. Search/filter
4. Apply
5. Referral request/acceptance
6. Event registration/check-in
7. Community membership
8. Moderation
9. Notifications
10. Messaging
11. Organization permissions

## Performance
Avoid N+1 queries, unbounded lists, large payloads, repeated expensive queries, and slow synchronous work. Use pagination, indexes, caching, aggregation, and Celery appropriately.

## Git
Use focused commits:
```text
feat: add opportunity publishing workflow
feat: add referral state machine
fix: prevent duplicate event registration
perf: optimize opportunity feed query
test: cover organization permissions
refactor: extract notification service
```

Do not mix unrelated changes or rewrite shared history unless explicitly requested.

## Development Workflow
Before a feature:
1. Understand the domain model.
2. Identify API, authorization, database, async, WebSocket, and frontend impact.
3. Add/adjust tests.
4. Implement the smallest coherent change.
5. Run tests, lint, and type checks.
6. Review security, permissions, transactions, and query count.
7. Update documentation when needed.

Preserve existing behavior and public APIs unless requirements explicitly change them.

## Definition of Done
A feature is normally complete only when it includes relevant backend, migration, permissions, validation, frontend, loading/error/empty states, tests, notifications/audit behavior where needed, security review, performance review, and Docker/local compatibility.

## Engineering Goal
Build a production-oriented SaaS system. Prioritize clear architecture, domain modeling, correctness, security, transactional consistency, scalability, observability, and maintainability. Do not add complexity merely to make the portfolio project look complex.
