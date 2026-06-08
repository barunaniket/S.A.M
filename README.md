# S.A.M — Smart Administrative Management

Backend API for an agentic faculty-scheduling platform. S.A.M is the single
operational interface used by a designated **teacher-in-charge** (SPOC) to
coordinate meetings, broadcasts, and calendar activity for the rest of the
faculty.

---

## 1. Operating Model: One Point of Contact

S.A.M is built around a strict **single-SPOC model**. Only one person — the
teacher-in-charge for a given organisation / department — authenticates with
the system. Everyone else is a *passive recipient*.

| Role | Authenticates? | Channels in | Channels out |
|------|----------------|-------------|--------------|
| **SPOC** (teacher-in-charge) | Yes — Google OAuth | Web frontend **and** WhatsApp | All API actions, calendar writes, broadcasts |
| **Faculty / participants** | No | None | Email, Google Calendar invite, WhatsApp message |

What this means in practice:

- The SPOC issues every command — create/reschedule/cancel meetings, run
  broadcasts, ingest faculty rosters, query availability.
- Other faculty receive `.ics` calendar invites, transactional emails, and
  optional WhatsApp messages. **They do not log in, do not RSVP through S.A.M,
  and do not message the bot back.** Inbound replies on WhatsApp are ignored
  by the orchestrator unless they originate from the SPOC's verified number.
- The SPOC can drive S.A.M from either the web frontend or by messaging the
  WhatsApp business number — both surfaces hit the same intent router and
  produce the same side effects.
- All audit rows, calendar events, and notifications are attributed to the
  SPOC's identity (`user_id`, `org_id`) carried in the JWT.

---

## 2. What S.A.M Does

- **Natural-language meeting orchestration** — the SPOC types or messages a
  request (`"meet Dr. Sharma and Prof. Kumar Friday 3pm about exam review"`);
  the LLM extracts intent, participants, and time, then drives the right
  service.
- **Faculty resolution** — fuzzy matches names against the faculty roster
  (loaded from CSV/XLSX/PDF/DOCX uploads) and resolves them to email +
  WhatsApp number.
- **Conflict-aware scheduling** — checks the SPOC's Google Calendar via
  freebusy before writing events; suggests alternative slots on conflict.
- **Calendar writes** — creates events with Google Meet links, supports
  reschedule/cancel, and runs a self-healing sync that reconciles drift
  between Google and the local DB.
- **Multi-channel notifications** — transactional email (Gmail SMTP), HTML
  meeting invites with `.ics` attachments, and WhatsApp messages via the
  Meta Cloud API. Broadcasts target individuals or named groups.
- **Faculty groups** — the SPOC can define groups (e.g. "CSE-Year-2") and
  broadcast to them in one shot.
- **Daily agenda + analytics** — generates a per-day briefing for the SPOC
  and surfaces meeting-load analytics.
- **Audit trail** — every action is row-logged with org-scoped RLS.

---

## 3. Architecture

```
                    ┌─────────────────────────────┐
   SPOC (web)  ─────►                             │
                    │     FastAPI (src/main.py)   │
   SPOC (WA)   ─────►   • JWT middleware          │
                    │   • Intent router           │
                    │   • Route modules           │
                    └────────────┬────────────────┘
                                 │
            ┌────────────────────┼────────────────────────┐
            ▼                    ▼                        ▼
   ┌────────────────┐  ┌────────────────────┐   ┌───────────────────┐
   │ PostgreSQL     │  │ Redis              │   │ External APIs     │
   │ • users        │  │ • email queue      │   │ • Google OAuth    │
   │ • meetings     │  │ • WA queue         │   │ • Google Calendar │
   │ • faculty      │  │ • locks / cache    │   │ • Gmail SMTP      │
   │ • groups       │  │ • conversation     │   │ • WA Cloud API    │
   │ • audit_logs   │  │   store            │   │ • NVIDIA / Gemini │
   └────────────────┘  └────────────────────┘   └───────────────────┘
                                 ▲
                                 │
                       ┌─────────┴──────────┐
                       │ Celery worker      │
                       │ (src/worker.py)    │
                       └────────────────────┘
```

Key design choices:

- **Auth**: Google OAuth → server-issued JWT (`user_id`, `org_id`, `email`).
  Refresh tokens are encrypted with Fernet before being persisted.
- **Multi-tenant isolation**: every request sets a Postgres session var
  (`app.org_id`) used by Row-Level Security policies.
- **Worker protocol**: every service returns
  `{success, data, message, error_code}` so the intent router and routes
  don't need bespoke error handling per service.
- **LLM**: NVIDIA OpenAI-compatible endpoint (default
  `meta/llama-3.3-70b-instruct`); Gemini supported as a fallback.
- **WhatsApp inbound**: Meta verifies via `/webhooks/whatsapp`; the
  orchestrator drops messages that don't come from the SPOC's verified
  number.

---

## 4. Tech Stack

| Layer | Tool |
|------|------|
| Language | Python 3.11 (Docker target) / 3.14 also works locally |
| API framework | FastAPI + Uvicorn |
| Auth | Google OAuth 2.0, PyJWT, `cryptography` (Fernet) |
| Datastore | PostgreSQL 15 (psycopg2 pool, RLS) |
| Cache / queue | Redis 7 |
| Background work | Celery |
| LLM | NVIDIA inference API (Llama 3.3 / Gemma); Gemini optional |
| Calendar | Google Calendar API (`google-api-python-client`) |
| Email | Gmail SMTP (`smtplib`, SSL :465), `icalendar` for `.ics` |
| WhatsApp | Meta Cloud API (`httpx`) |
| File ingestion | `pandas`, `openpyxl`, `pypdf`, `python-docx` |
| Fuzzy matching | `thefuzz` |

---

## 5. API Surface

All routes except `/`, `/auth/*`, `/webhooks/*`, `/docs`, `/openapi.json`,
and `/redoc` require a `Bearer` JWT.

### Auth
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/auth/login-url` | Returns the Google OAuth URL the SPOC visits |
| POST | `/auth/callback` | Exchanges OAuth code → JWT + user record |

### Meetings
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/meetings` | Create meeting (calendar + invites) |
| PATCH | `/api/v1/meetings/{id}` | Reschedule |
| DELETE | `/api/v1/meetings/{id}` | Cancel |
| POST | `/api/v1/meetings/search` | DB-side search |

### Scheduling intelligence
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/availability` | Free-slot calculator (freebusy) |
| GET | `/api/v1/agenda?date=YYYY-MM-DD` | Daily briefing for the SPOC |
| GET | `/api/v1/analytics/meetings` | Meeting-load analytics |
| POST | `/api/v1/calendar/sync` | Self-healing Google ↔ DB reconcile |

### Natural language
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/process` | Parse SPOC text → structured intent |
| POST | `/api/v1/process/execute` | Run a parsed intent |
| POST | `/api/v1/process/clarify` | Disambiguate when intent is ambiguous |

### Notifications + email
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/notifications` | Create notification record |
| GET | `/api/v1/notifications/{user_id}` | List notifications |
| PATCH | `/api/v1/notifications/{id}/read` | Mark read |
| POST | `/api/v1/email/send` | Direct send (transactional) |
| POST | `/api/v1/email/queue` | Enqueue for the worker |
| POST | `/api/v1/email/notify` | HTML meeting invite + `.ics` |
| WS | `/api/v1/ws/notifications/{user_id}` | Live push to the SPOC UI |

### Faculty data + groups
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/uploads` | Ingest faculty roster (CSV/XLSX/PDF/DOCX) |
| GET / POST | `/api/v1/groups` | List / create groups |
| DELETE | `/api/v1/groups/{id}` | Delete group |
| GET / POST | `/api/v1/groups/{id}/members` | Manage members |
| DELETE | `/api/v1/groups/{id}/members/{user_id}` | Remove member |

### WhatsApp (SPOC-only inbound)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/webhooks/whatsapp` | Meta webhook verification |
| POST | `/webhooks/whatsapp` | Inbound messages — accepted only from the SPOC's verified number |

### Lifecycle (experimental state machine)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/experimental/meeting/{id}` | Create via state machine |
| PATCH | `/api/v1/experimental/meeting/{id}/schedule` | Schedule transition |
| DELETE | `/api/v1/experimental/meeting/{id}` | Cancel transition |

### Health
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Liveness |
| GET | `/api/v1/health` | Deep health (DB + Redis + LLM + Google reach) |

---

## 6. Setup

### 6.1 Prerequisites
- Docker + Docker Compose (recommended), or
- Python 3.11 + Postgres 15 + Redis 7 (manual)
- Google Cloud project with Calendar API enabled and an OAuth client
- Gmail account with an App Password (or institutional SMTP)
- Meta WhatsApp Business app (phone number ID, access token, app secret) —
  optional in dev (stub values are accepted)
- NVIDIA API key (or Gemini API key as fallback)

### 6.2 Environment
Copy the keys below into `.env` at the repo root. Treat this file as a
secret — never commit real values.

```env
# Google
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_PROJECT_ID=...
GOOGLE_REDIRECT_URI=http://localhost:3000/auth/callback
GOOGLE_API_SCOPES=https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly email profile

# LLM
NVIDIA_API_KEY=...
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL_ID=meta/llama-3.3-70b-instruct
GEMINI_API_KEY=                  # optional

# WhatsApp (Meta Cloud API) — use "stub" in dev
WHATSAPP_PHONE_NUMBER_ID=stub
WHATSAPP_ACCESS_TOKEN=stub
WHATSAPP_VERIFY_TOKEN=stub
WHATSAPP_APP_SECRET=stub
WHATSAPP_GRAPH_VERSION=v20.0

# Email
SENDER_EMAIL=...
SENDER_PASSWORD=...              # Gmail app password

# Database
DATABASE_URL=postgresql://postgres:postgres@db:5432/sam
DB_USER=postgres
DB_PASSWORD=postgres
DB_NAME=sam
DB_HOST=db
DB_PORT=5432

# Redis
REDIS_URL=redis://redis:6379/0

# Auth
SECRET_KEY=<openssl rand -hex 32>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
ENCRYPTION_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# App
APP_PORT=8000
DEBUG=True
UPLOAD_DIR=data/uploads
```

### 6.3 Run the API stack with Docker (recommended)
```bash
docker compose up -d --build
```
Brings up Postgres, Redis, the FastAPI backend (`:8000`), and the Celery
worker. See `DOCKER.md` for tear-down, logs, and migration tips.

> The frontend deliberately does **not** run in Docker. Next.js's file
> watcher and `.next` build cache are unreliable when served over this
> repo's bind-mounted NTFS path, which produced silent compile failures
> and stale chunks. Running it natively on the host is the supported
> dev workflow.

### 6.4 Run the frontend on your host
```bash
cd frontend
cp .env.local.example .env.local   # first time only
npm install                        # first time only
npm run dev                        # http://localhost:3000
```

### 6.5 Run the backend without Docker (optional)
If you'd rather skip Docker for the API too:
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Initialise schema (first time only)
python scripts/reset_db.py
python scripts/init_meetings_tables.py
python scripts/migrate_v3_features.py
python scripts/migrate_phone_and_student.py
python scripts/seed_db.py          # optional sample data

uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```
You'll still need a Postgres and Redis reachable at the URLs in `.env`.

Once both tiers are running:
- SPOC dashboard:   `http://localhost:3000`
- API docs:         `http://localhost:8000/docs`

---

## 7. Typical SPOC Workflow

1. **Login** — SPOC visits the web frontend, hits `/auth/login-url`, completes
   Google OAuth, and receives a JWT.
2. **Roster upload** — POSTs faculty list to `/api/v1/uploads`. S.A.M parses
   CSV/XLSX/PDF/DOCX, dedupes, and stores email + phone per faculty.
3. **(Optional) Define groups** — `/api/v1/groups` for repeated broadcast
   targets.
4. **Drive S.A.M** — either:
   - Web: SPOC types into the chat box → frontend → `/api/v1/process` →
     `/api/v1/process/execute`.
   - WhatsApp: SPOC messages the bot number → Meta webhook →
     orchestrator → same intent path.
5. **S.A.M acts** — resolves participants, checks calendar conflicts,
   creates the event with a Meet link, dispatches `.ics` invites by email,
   optionally fans out a WhatsApp notice.
6. **Recipients** — get the email/calendar invite/WhatsApp message. They do
   nothing in S.A.M; their RSVP (if any) happens inside Google Calendar.
7. **Audit** — every step is row-logged under the SPOC's `user_id` /
   `org_id`.

---

## 8. Repository Layout

```
src/
  main.py                 # FastAPI app, middleware, router registration
  worker.py               # Celery entrypoint
  api/
    routes/               # one module per resource
    lifecycle_routes.py   # experimental meeting state machine
  services/               # business logic — meeting, broadcast, ingestion, WA
  utils/                  # config, db, google_auth, middleware, etc.
frontend/                 # Next.js 14 SPOC dashboard
  app/                    # routes (login, /app shell, settings, …)
  components/             # ui primitives + feature components
  lib/                    # api client, auth, ws helpers
  hooks/                  # useAuth, useAgenda, useGoogleStatus
scripts/                  # DB init / migration / seed scripts
tests/                    # pytest suite
data/uploads/             # ingested faculty files
```

### Frontend (SPOC dashboard)

The `frontend/` folder is a self-contained Next.js 14 app (App Router,
TypeScript, Tailwind, lean shadcn-style primitives) that ships the only
human-facing surface for S.A.M.

- **Stack:** Next.js 14, React 18, TypeScript, Tailwind, SWR, Sonner, Lucide.
- **Routes:**
  - `/`               → redirects to `/app` or `/login` based on JWT
  - `/login`          → "Connect Google Calendar" CTA (no passwords)
  - `/auth/callback`  → exchanges OAuth code → JWT, redirects to `/app`
  - `/app`            → two-pane shell: sidebar nav + Chat homepage with today's agenda strip
  - `/app/settings`   → Google connection status, account, about
  - `/app/{meetings,faculty,groups,broadcasts}` → reserved for v2 (driven via Chat today)
- **Auth:** JWT in `localStorage` (`sam_jwt`); `lib/api.ts` attaches it as
  `Bearer` and unwraps the worker-protocol envelope automatically.
- **Live updates:** opens a WebSocket to
  `/api/v1/ws/notifications/{user_id}` and renders incoming messages as
  system bubbles in chat.
- **OAuth status pill:** polls `GET /api/v1/me/google-status` every 60s
  to show green/amber/red in the header.

Env vars (`frontend/.env.local`):
```
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_PUBLIC_WS_BASE=ws://localhost:8000
```

---

## 9. Testing

```bash
pytest                            # full suite
pytest tests/test_endpoints.py    # HTTP route smoke tests
pytest -k whatsapp                # filter by keyword
```

Targets:
- ≥95% participant resolution accuracy on the seeded roster
- ≥90% conflict detection on overlapping events
- < 3s p95 for `/api/v1/process` end-to-end

---

## 10. Operational Notes

- **Adding a new SPOC** — insert a row into `users` with `role = 'spoc'`
  and the appropriate `org_id`; the OAuth flow will populate
  `access_token` / `encrypted_refresh_token` on first login.
- **Rotating `ENCRYPTION_KEY`** — re-encrypt all `encrypted_refresh_token`
  rows; old tokens become unreadable otherwise.
- **WhatsApp identity** — the SPOC's verified phone number must be stored
  on their `users` row; the orchestrator hard-rejects inbound messages
  from any other number.
- **LLM swap** — change `NVIDIA_MODEL_ID` in `.env`; see the comment block
  in `.env` for tested alternatives and their trade-offs.

---

## 11. License

See `LICENSE`. Open for academic and experimental use.
