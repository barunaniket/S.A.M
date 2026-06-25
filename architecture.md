# S.A.M — Architecture

## Overview

S.A.M (Smart Administrative Messenger) is a multi-tenant, agentic backend for faculty-scheduling. It follows a strict **single-SPOC model** — one teacher-in-charge authenticates and drives all actions via a web frontend or WhatsApp, while other faculty are passive recipients of calendar invites, emails, and WhatsApp messages.

---

## System Diagram

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

---

## Components

### 1. API Layer — FastAPI (`src/main.py`)
- JWT middleware protecting all routes except auth, webhooks, and docs
- Intent router that parses SPOC natural-language commands
- Route modules for meetings, availability, notifications, faculty, groups, uploads, WhatsApp webhooks, and experimental lifecycle

### 2. Database — PostgreSQL 15
- Tables: `users`, `meetings`, `faculty`, `groups`, `group_members`, `notifications`, `audit_logs`
- Row-Level Security (RLS) with org-scoped isolation via `app.org_id` session variable
- Parameterized queries via `psycopg2` connection pool

### 3. Cache & Queue — Redis 7
- Email and WhatsApp dispatch queues consumed by the Celery worker
- Distributed locks and general caching
- Conversation store for multi-turn LLM interactions

### 4. Background Worker — Celery (`src/worker.py`)
- Processes queued email sends, WhatsApp messages, and calendar sync jobs
- Decouples long-running I/O from the request-response path

### 5. External Integrations
| Service | Purpose |
|---------|---------|
| Google OAuth 2.0 | SPOC authentication; refresh tokens encrypted with Fernet |
| Google Calendar API | FreeBusy conflict checks, event CRUD, Meet link generation |
| Gmail SMTP | Transactional email with `.ics` attachments via `icalendar` |
| Meta Cloud API | WhatsApp outbound broadcasts and inbound SPOC messages |
| NVIDIA Inference API | Default LLM (Llama 3.3 70B); Gemini as fallback |

---

## Data Flow (Typical Request)

```
SPOC input (web or WA)
    → FastAPI receives request
    → JWT middleware authenticates + sets org context
    → Intent router parses NL via LLM → structured intent
    → Service layer:
        1. Resolve participants (fuzzy match against faculty roster)
        2. Check calendar conflicts (Google FreeBusy API)
        3. Create/update event on Google Calendar
        4. Persist to PostgreSQL
        5. Enqueue notifications on Redis
    → Celery worker dispatches email + WhatsApp
    → Response returned to SPOC
```

---

## Key Design Decisions

- **Unified response envelope**: All services return `{success, data, message, error_code}` for consistent error handling
- **SPOC-only inbound**: WhatsApp webhook drops any message not from the SPOC's verified number
- **Fail-safe conflicts**: If Google Calendar API fails, default to assuming a conflict
- **Self-healing sync**: Periodic reconciliation between Google Calendar state and local DB
- **Multi-tenancy**: Row-level security driven by `org_id` from JWT, no shared data leakage

---

## Repository Layout

```
src/
  main.py                 # FastAPI app, middleware, router registration
  worker.py               # Celery entrypoint
  api/
    routes/               # One module per resource
    lifecycle_routes.py   # Experimental meeting state machine
  services/               # Business logic — meeting, broadcast, ingestion, WA
  utils/                  # Config, db, google_auth, middleware, etc.
frontend/                 # Next.js 14 SPOC dashboard
scripts/                  # DB init / migration / seed scripts
tests/                    # Pytest suite
```
