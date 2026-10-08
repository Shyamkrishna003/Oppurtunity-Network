# Opportunity Network

A multi-tenant platform where people, organizations, and communities publish, distribute, discover, and act on professional opportunities (jobs, events, referrals), and track the outcome.

- Product requirements: [PRD.md](PRD.md)
- Engineering rules: [CLAUDE.md](CLAUDE.md)
- Architecture and roadmap: [docs/architecture/implementation-plan.md](docs/architecture/implementation-plan.md)

## Status

Phases 0 and 1 are done. What works today:

- Accounts: register, confirm email, sign in, stay signed in across reloads, sign out, reset and change password.
- Profiles: details, photo, skills and interests, experience, education, privacy settings, blocking.

Organizations and communities are next (Phase 2).

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
├── users/    accounts, sessions, profiles, experience/education, blocks
├── taxonomy/ shared skill list
└── audit/    append-only AuditLog and record()
```

Each domain app follows the same layering: `models.py` (schema and constraints), `policies.py` (permission rules), `selectors.py` (scoped reads), `services.py` (all writes and state transitions), `api/` (serializers, views, URLs), `tasks.py` (Celery wrappers).

## Conventions

- Every API error uses one envelope: `{type, title, status, code, detail, errors, request_id}`.
- Every response carries `X-Request-ID`; the same ID appears in backend logs, Celery task logs, and audit records.
- Sessions: a 10-minute access token kept in memory by the web app, plus a rotating refresh token in an `HttpOnly` cookie sent only to `/api/v1/auth/`. Reusing a rotated refresh token ends that session.
- Emails are sent by the Celery worker. Locally, read them in Mailpit (http://localhost:8025) to follow confirmation and reset links.
- Configuration comes from environment variables only. `.env` is git-ignored; never commit real secrets.
