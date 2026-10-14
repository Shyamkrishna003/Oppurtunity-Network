# Opportunity Network

A multi-tenant platform where people, organizations, and communities publish, distribute, discover, and act on professional opportunities (jobs, events, referrals), and track the outcome.

- Product requirements: [PRD.md](PRD.md)
- Engineering rules: [CLAUDE.md](CLAUDE.md)
- Architecture and roadmap: [docs/architecture/implementation-plan.md](docs/architecture/implementation-plan.md)

## Status

Phases 0 to 8 are done. What works today:

- Accounts: register, confirm email, sign in, stay signed in across reloads, sign out, reset and change password.
- Profiles: details, photo, skills and interests, experience, education, privacy settings, blocking.
- Organizations: create, invite by email, roles (owner, admin, recruiter, member), remove, leave, transfer ownership.
- Communities: public or private; open, approval or invitation-only joining; roles (owner, admin, moderator, member); requests, invitations, removal, bans; rules.

- Jobs: post personally or for an organization, publish, edit within limits, close, archive; jobs past their deadline expire automatically.
- Distribution: share a job with communities; each community approves, rejects, removes or pins it independently.
- Discovery: a feed with full-text search (typo-tolerant), filters kept in the address so searches can be shared, and "best match" ranking from your skills, interests, communities, location and work mode, with the reasons shown. Saved opportunities.
- Notifications: in the app and by email for invitations, membership decisions, review requests and decisions about your opportunities, with per-category preferences. They appear live over a WebSocket (`/ws/stream/`), which is only ever a hint: every notification is stored first, so nothing is lost if the connection, the worker or the browser is away.

- Applications: apply to a job with a PDF resume and a note, follow each application under "My applications", and withdraw. Resumes are stored privately and downloaded only through links that expire after a minute.
- Hiring pipeline: whoever manages a job sees its applications by stage (applied, screening, shortlisted, interview, offer, hired, not selected), moves them forward or rejects them, and can leave notes that only the hiring team reads. Applicants are told of each move in the app, by email and live. A move made on an out-of-date page is refused rather than overwriting a colleague's decision.

- Connections: ask someone to connect from their profile, accept or decline requests, take a request back, end a connection. Your list is yours alone: nobody can browse another person's connections. A decline is never announced to whoever asked, blocking someone ends the connection, and a "connections only" profile now opens for connections.

- Referrals: on an organization's job, ask one of your own connections who works there to refer you. They accept or decline, then make the referral with a note for the people hiring, who see it next to your application. From then on the referral follows the application to its outcome (interview, offer, joined). Only your own connections who show their membership publicly and take referral requests are offered, and every refusal reads the same, so asking cannot reveal who works where. Unanswered requests expire after 14 days.

- Events: host an event personally or for an organization, in person, online or both, with its times kept in the event's own time zone. Publish, edit within limits, cancel; events appear in the feed next to jobs and can be filtered. Registration opens and closes and events complete by themselves as their times pass. Register for a place, or join the waitlist when an event is full: the place freed by a cancellation goes at once to whoever waited longest, who is told in the app, by email and live. Organizers see who is coming, can remove a registration, change the number of places, and close or reopen registration; cancelling an event tells everyone registered. The link to join online is only shown to the people running the event and to those holding a place, and the attendee list to whoever the organizers chose. Everyone going is reminded the day before and an hour before. At the door, each attendee shows a QR code from the event's page and an organizer scans it (or pastes it) on the check-in screen; the code is signed by the server, works once, only for that event, and stops working if the place is given up.

- Messages: private one-to-one conversations with your connections, started from a profile. Messages arrive live, the inbox shows what is unread, and "Seen" shows how far the other person has read. A message appears at once while it is being sent, and a retry can never send it twice. Blocking someone makes the conversation vanish for both.

- Moderation (Phase 9): report a person, organization, community or opportunity from its page. Platform moderators work through a queue: take a report, dismiss it, or hide or remove a reported opportunity with a reason its owners see. Hiding can be undone; every action is recorded. Whoever reported is never named to the reported, and the reporter is told only that their report was reviewed. Staff also get a "Moderate this …" link on every profile, organization, community and opportunity page, leading to a page with its standing, its history and what can be done now: warn a person, stop them posting, or suspend them (either until a date or until lifted); suspend an organization or community; mark an organization verified. Suspending and verifying are for platform admins only; nobody can act on themselves, and only an admin can act on other staff. A suspended person is signed out everywhere at once and cannot sign in, refresh a session or open the live connection until it ends.
- Community moderation: a member can send a report about an opportunity to the moderators of a community that shows it, instead of the platform's. Those moderators have their own queue (`/communities/:id/reports`) and can dismiss the report, take the opportunity out of their community only, or pass the report up to the platform. They never see who reported, cannot decide a report about something they manage, and platform staff have no access to a community's queue.
- Audit log: platform admins can search every recorded action by person, action or target (`/admin/audit`). Owners of an organization or a community get an activity log of their own tenant, limited to its own business.
- Admin dashboard (`/admin`): counts of outcomes (applications, hires, event attendance, referrals), opportunities, people, organizations, communities and waiting reports, computed in the database and kept for a minute.

A user can belong to any number of organizations and communities, with a different role in each.

## Stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite, React Router, TanStack Query, Redux Toolkit |
| Backend | Python 3.14, Django 5.2, Django REST Framework, Channels, Celery |
| Data | PostgreSQL 17, Redis 7 |
| Local infrastructure | Docker Compose, Nginx, Mailpit |

## Run locally

Requires Docker with Compose.

```bash
cp .env.example .env
docker compose up --build
```

Everything is served from one origin through Nginx:

| URL | What |
|---|---|
| http://localhost:8080/ | Web app |
| http://localhost:8080/api/v1/schema/ | OpenAPI schema |
| http://localhost:8080/admin/ | Django admin |
| http://localhost:8080/healthz | Liveness |
| http://localhost:8080/readyz | Readiness (database, cache, migrations) |
| http://localhost:8025/ | Mailpit inbox for outgoing email |

Change `HTTP_PORT` in `.env` to use another port (update `DJANGO_CSRF_TRUSTED_ORIGINS` to match).

Create an admin account:

```bash
docker compose exec backend python manage.py createsuperuser
```

## Services

| Service | Role |
|---|---|
| `nginx` | Single entry point: SPA, `/api/`, `/admin/`, `/ws/` |
| `backend` | Django ASGI server (HTTP and WebSocket in development) |
| `worker` | Celery worker for all queues |
| `beat` | Celery scheduler; run exactly one |
| `migrate` | One-shot: applies migrations before the app starts |
| `frontend` | Vite dev server with hot reload |
| `postgres`, `redis` | Datastores (Redis: db 0 cache, db 1 Celery broker, db 2 channel layer) |
| `mailpit` | Captures outgoing email |

Uploaded files go through Django's storage API. Locally they are written to `backend/media/` (git-ignored) and served at `/media/`; production points the same setting at S3-compatible storage.

## Checks

Backend (inside the container):

```bash
docker compose exec backend ruff check .
docker compose exec backend ruff format --check .
docker compose exec backend mypy .
docker compose exec backend pytest
docker compose exec backend python manage.py makemigrations --check --dry-run
docker compose exec backend python manage.py spectacular --validate --fail-on-warn --file /tmp/schema.yml
```

Frontend (Node 24 on the host, or prefix with `docker compose exec frontend`):

```bash
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

## Backend layout

```text
backend/
├── config/   settings (base/dev/test/prod), URLs, ASGI, Celery, logging
├── common/   base models, error envelope, pagination, request context, state machine, health
├── users/         accounts, sessions, profiles, experience/education, blocks
├── taxonomy/      shared skill list
├── organizations/ organizations, members, email invitations
├── communities/   communities, membership state machine, rules
├── opportunities/ shared opportunity record, lifecycle, visibility, sharing, feed, relevance
├── jobs/          job-specific detail, one-to-one with its opportunity
├── connections/   one row per pair of people: requested, accepted or declined
├── referrals/     referral requests on a job, their workflow, and tracking of the outcome
└── audit/         append-only AuditLog and record()
```

Each domain app follows the same layering: `models.py` (schema and constraints), `policies.py` (permission rules), `selectors.py` (scoped reads), `services.py` (all writes and state transitions), `api/` (serializers, views, URLs), `tasks.py` (Celery wrappers).

## Conventions

- Every API error uses one envelope: `{type, title, status, code, detail, errors, request_id}`.
- Every response carries `X-Request-ID`; the same ID appears in backend logs, Celery task logs, and audit records.
- Sessions: a 10-minute access token kept in memory by the web app, plus a rotating refresh token in an `HttpOnly` cookie sent only to `/api/v1/auth/`. Reusing a rotated refresh token ends that session.
- Tenancy: organizations and communities are tenants. Every change one person makes to another's membership locks the tenant row first, checks permission, and writes an audit record; an organization or community can never be left without an owner.
- Discovery is deterministic: relevance is a fixed sum over what the user entered (5 per matching skill, 3 per interest, 3 for a community they belong to, 2 for location, 2 for work mode), computed in SQL for ordering and explained per result. No machine learning.
- Emails are sent by the Celery worker. Locally, read them in Mailpit (http://localhost:8025) to follow confirmation and reset links.
- Configuration comes from environment variables only. `.env` is git-ignored; never commit real secrets.
