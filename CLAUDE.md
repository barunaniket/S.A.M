# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Use the graphify index before searching

A persistent knowledge graph of this codebase lives in `graphify-out/`. Treat it as the project's RAG layer — consult it **before** spelunking with grep/find, and refresh it after non-trivial changes.

- `graphify-out/graph.json` — 1,196 nodes / 2,160 edges spanning code, docs, and the unfiltered design PDFs. Load with `networkx.readwrite.json_graph.node_link_graph(..., edges='links')`.
- `graphify-out/GRAPH_REPORT.md` — community map, god nodes (`Config`, `get_db_connection`, `release_db_connection`, `LLMProcessor`, `route_intent`), surprising cross-doc/code links, and suggested questions.
- `graphify-out/graph.html` — interactive visualization for the human in the loop.

Workflow:

- For "where is X / what touches Y / how does flow Z work" questions, run `/graphify query "<question>"` (BFS) or `--dfs` (chain trace) instead of guessing keywords. Use `/graphify path A B` to get the shortest concept path between two ideas, and `/graphify explain "<node>"` for a single-node neighborhood.
- After landing code changes, run `/graphify . --update` to re-extract only changed files. Code-only changes skip the LLM (AST + cluster only); doc/PDF changes need the semantic pass.
- Edges carry confidence: `EXTRACTED` (1.0, structural), `INFERRED` (0.6–0.9, model-reasoned), `AMBIGUOUS` (0.1–0.3). Don't quote `INFERRED` edges as facts without verifying the underlying file.

## Single-SPOC operating model (read this before changing auth or routing)

S.A.M is built around one authenticated user per org — the teacher-in-charge ("SPOC"). Everyone else (faculty, students) is a passive recipient who gets `.ics` invites, transactional email, or WhatsApp messages but **never logs in and never sends commands**. The orchestrator hard-rejects inbound WhatsApp from any number that isn't the SPOC's verified one. Multi-tenant isolation is enforced by setting Postgres session var `app.org_id` per-request, which RLS policies key off — middleware in `src/utils/middleware.py` is the single chokepoint.

The v4–v8 release expanded this with role-aware extensions: `SUPER_ADMIN`, `BOOKING_AUTHORITY`, `FACULTY`, `STUDENT`. Roles are baked into the JWT claim — **users must log out and back in after a role change** for it to take effect. RBAC enforcement uses `src/utils/rbac.py` (`has_role`, `require_roles` FastAPI dependency).

> Pre-v1 routes (meetings, groups, broadcasts, analytics) have JWT auth but **no role guard yet** — RBAC backfill is a known gap. New v4–v8 routes (`bookings`, `tasks`, `timetable`, `academic_calendar`, `admin_users`, `preferences`) are all gated.

## Architecture in one breath

- **API**: FastAPI (`src/main.py`) → JWT middleware → `src/services/intent_router.py` for natural-language → handler dispatch.
- **Worker**: Celery (`src/worker.py`) consumes Redis queues for email + WhatsApp fan-out; `beat` container ticks `tick_user_briefings` every 5 min.
- **Datastore**: PostgreSQL 15 with row-level security per `org_id`; Redis 7 for queues, distributed locks (`src/utils/concurrency.py`), and the conversation store.
- **LLM**: NVIDIA OpenAI-compatible endpoint (`meta/llama-3.3-70b-instruct` default); Gemini optional. `src/services/llm_processor.py` extracts intent; `src/services/clarification_agent.py` disambiguates.
- **External**: Google Calendar (events + freebusy + self-healing reconcile in `src/utils/self_healing_calendar.py`), Gmail SMTP for `.ics` invites, Meta WhatsApp Cloud API.
- **Multimodal ingest**: Tesseract OCR + faster-whisper transcription via `src/services/media_transcriber.py` and `src/services/file_ingestor.py` for rosters, timetable photos, voice memos.
- **Service contract**: every service returns `{success, data, message, error_code}`. The intent router and routes rely on this shape — don't introduce a service that raises raw exceptions to the caller; catch and envelope.
- **Service Function Pattern**: validate → resolve dependencies → act → return enveloped result. See `src/services/meeting_creator.py` as the canonical example.

## Frontend

`frontend/` is a Next.js 14 (App Router, TypeScript, Tailwind, lean shadcn primitives). It runs **natively on the host, not in Docker** — the NTFS bind-mount under WSL/Windows breaks Next.js's `.next` cache and produces stale chunks. JWT lives in `localStorage.sam_jwt`; `lib/api.ts` attaches Bearer and unwraps the worker-protocol envelope. WebSocket at `/api/v1/ws/notifications/{user_id}` for live updates. OAuth health pill polls `GET /api/v1/me/google-status` every 60s. Sidebar is role-aware via `frontend/components/auth/RoleGuard.tsx`.

## Common commands

### Backend stack (Docker, recommended)
```bash
docker compose up -d --build       # API :8000, Postgres, Redis, Celery worker, beat
docker compose logs -f beat        # confirm "tick_user_briefings: dispatched N"
```

### Frontend (host)
```bash
cd frontend && npm run dev         # http://localhost:3000
```

### Migrations — must run in order
```bash
python scripts/reset_db.py                          # destructive, dev only
python scripts/init_meetings_tables.py
python scripts/migrate_v3_features.py
python scripts/migrate_phone_and_student.py
python scripts/migrate_v4_foundations.py
python scripts/migrate_v5_timetable.py
python scripts/migrate_v6_academic_calendar.py
python scripts/migrate_v7_tasks.py
python scripts/migrate_v8_booking_briefing.py
python scripts/seed_db.py                           # optional sample data
```
After v4+: re-login so the JWT picks up the new `role` claim.

### Tests
```bash
pytest                                   # full suite (modern)
pytest tests/test_endpoints.py           # HTTP route smoke tests
pytest -k whatsapp                       # filter by keyword
python -m unittest tests.test_conflict_detector.TestConflictDetector.test_conflict_exists  # legacy single-test path still works
```

### Backend without Docker
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```
Tesseract is a system dep on host runs: `sudo dnf install -y tesseract` (Fedora) / `apt install tesseract-ocr` (Debian).

## Things that have bitten us

- **Frontend in Docker** — don't try. NTFS bind-mount + Next.js cache = silent stale chunks.
- **Whisper cold start** — model files (~150 MB) download on first call. Pre-pull to `SAM_WHISPER_MODEL_DIR` for production.
- **Class cancellation broadcasts** require a `user_groups` row whose `name` matches the timetable entry's batch (e.g. `CSE-3A`). Create groups manually via `/app/groups` until auto-enrolment ships.
- **`ENCRYPTION_KEY` rotation** — every `users.encrypted_refresh_token` must be re-encrypted; otherwise refresh tokens are unreadable and the SPOC silently loses Calendar access.
- **Faculty name disambiguation** triggers a clarification prompt when the top two `thefuzz` candidates are within 6 points. In large orgs with common names, expect to add manual hints.
- **OCR timetables** from phone cameras are lossy — the editable grid in `/app/timetable/upload` and the WhatsApp confirm step are the safety net, not optional polish.

## Conventions worth respecting

- Absolute imports (`from src.services.meeting_creator import ...`) — relative imports are not used.
- Every service returns the envelope; routes unwrap it. Don't bypass.
- Fail-safe defaults on external API failure (e.g. assume conflict if Google Calendar errors). Conflict detector and freebusy checks all follow this.
- Parameterized queries only. Helper is `get_db_connection()` from `src/utils/db_handler.py`; always pair with `release_db_connection()` in `finally`.
- Every action that mutates state writes an audit row scoped to the SPOC's `user_id` / `org_id`.
