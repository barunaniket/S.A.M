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
- **Worker**: Celery (`src/worker.py`) consumes Redis queues for email + WhatsApp + Telegram fan-out; `beat` container ticks `tick_user_briefings` every 5 min.
- **Telegram channel**: mirrors the WhatsApp surface 1:1 — `telegram_service.py`, `telegram_queue.py`, `telegram_orchestrator.py`, `telegram_poller.py` (long-poll worker, no public webhook needed). Pairing flow: `/api/v1/me/telegram/pair` issues a 6-char code; user DMs `/start CODE` to bind `users.telegram_chat_id`. Same `intent_router`, `file_ingestor`, and `whatsapp_audit` (with `channel='telegram'`) — no new abstractions.
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
python scripts/migrate_v9_telegram.py
python scripts/migrate_v10_demo.py
python scripts/migrate_v11_mcq.py
python scripts/migrate_v12_mvp.py
python scripts/migrate_v13_spec.py
python scripts/seed_demo.py                         # minimal demo cast (SPOC + Priya/Rahul + Arjun/Riya)
python scripts/load_rosters.py --timetables        # full synthetic rosters from data/*.csv
```

`load_rosters.py` reads `data/students.csv` + `data/faculty.csv` (+ `data/timetable.csv`
when `--timetables` is passed). It UPSERTs users, refreshes class user_groups for every
distinct batch, and is idempotent — re-running after a CSV edit just applies the diff.
After v4+: re-login so the JWT picks up the new `role` claim.

### Chat-first onboarding (Telegram, v10)

Anyone DMing the bot for the first time goes straight through Google OAuth — no
web pairing code needed. `telegram_orchestrator._start_chat_first_onboarding`
calls `services/onboarding.start_onboarding`, which writes an
`onboarding_tokens` row and returns a Google OAuth URL with
`state=onboard:tg:<token>`. The `/auth/callback` route detects that prefix and
routes through `complete_onboarding`, which matches the user by email against
the pre-seeded roster (institutional Gmail = verification), binds
`users.telegram_chat_id`, and pushes a welcome DM. Faculty without a timetable
land in `AWAITING_TIMETABLE`; students without a batch land in
`AWAITING_BATCH`. The web-first `/start CODE` pairing path is still wired in
parallel for users who came in via the web first.

### MCQ-based attendance (v11)

Faculty triggers a quiz at the end of class via `start mcq attendance for <subject>`.
`src/services/attendance_mcq.py` handles the lifecycle:

1. `start_session` inserts an `mcq_sessions` row (questions persisted as JSONB)
   and schedules N Celery `dispatch_mcq_question` tasks at +0s, +15s, +30s, …
   plus one `close_mcq_session` task at the end of the window.
2. Each dispatch fans out an inline-keyboard message to every paired student
   in `users` whose `batch` matches the session.
3. Student taps trigger `mcq_<sid>_<q>_<c>` callback queries handled in
   `telegram_orchestrator._handle_callback` → `record_answer` writes to
   `mcq_responses` (UNIQUE on session/user/q so retaps are no-ops).
4. `close_session` reads every response, scores each student against
   `questions[*].correct`, ignores responses that landed after the question's
   window, and writes one row per student to `attendance_records`
   (PRESENT if score ≥ threshold, default 4/5).
5. Faculty gets a Telegram DM with the full breakdown plus a hint —
   replying `mark <name> present|absent` triggers `override_attendance`
   which flips the record (and stamps `overridden=TRUE`).

Question source for the demo is hardcoded in `attendance_mcq.QUESTION_BANK`
(DSA, Compilers, Algorithms — 5 questions each). Replace with an
`mcq_question_bank` table for production.

### Period-aware faculty lookup (v10)

`src/utils/periods.py` hardcodes the bell schedule (1st 09:00-09:50, … 4th
12:00-12:50, lunch, 5th 14:00-14:50, …). The LLM `query_faculty_status` intent
now extracts `query_period` (1-8) and `query_day_keyword` ("today", "tomorrow",
weekday) alongside `query_time`. `intent_router` resolves the period to a
datetime, calls `who_is_busy_at`, and falls back to `users.office_location`
when the faculty has no class — "Dr Sharma doesn't have a class during 4th
period — she should be in Faculty Block, Room 312."

### v13 spec completion — read paths, PDF→MCQ, deadline nudges, dashboard

The v13 ship filled five gaps in the chat surface and dashboard:

1. **Read-path intents** in `src/services/intent_router.py`:
   `query_attendance_sheet`, `query_my_attendance`, `query_class_submissions`,
   `list_open_assignments_for_faculty`, `list_class_roster`. Faculty can now
   say "bring up CS201 attendance for today" / "who hasn't submitted assignment 3".
   Implementation in `src/services/attendance_query.py` + new helpers in
   `src/services/assignment_service.py`. Telegram-friendly HTML messages built
   in `src/utils/formatters.py`.

2. **PDF-curated MCQ generation** (`src/services/mcq_generator.py`). Faculty
   DMs a PDF with caption `material <subject>` (or uploads via
   `/app/super-admin/materials`); `course_materials.record_material` saves
   it with extracted text. `generate_mcq_attendance` LLM-drafts 5 MCQs;
   faculty taps Approve, future `start mcq attendance` calls pull from
   `mcq_question_bank` instead of the hardcoded `QUESTION_BANK` dict.

3. **Assignment deadline nudges** in `src/tasks/assignments.py` + Celery
   tasks `dispatch_assignment_nudge` and `close_assignment` registered in
   `src/worker.py`. `assignment_service.create()` now schedules nudges at
   `org_settings.assignment_nudge_hours` offsets (default `[24, 1]`).
   Students get an inline-keyboard `[Almost done] [I'll submit now]` —
   tapping the latter pre-fills the AWAITING_ASSN_FILE state so the next
   photo lands as the submission.

4. **Web dashboard pages** under `frontend/app/app/`:
   `faculty/attendance`, `faculty/assignments[ /[id] ]`,
   `super-admin/materials`, `super-admin/settings`. All gated via
   `RoleGuard`; backend by `/api/v1/{attendance,assignments,materials,settings}`
   in `src/api/routes/`.

5. **RBAC backfill** on `/meetings`, `/groups`, `/analytics` — these
   pre-v1 routes had JWT auth but no role guard. New routes are checked
   automatically by `scripts/audit_route_rbac.py` (run in CI; tracks a
   shrinking "known ungated" list for the remaining legacy routes).

Per-org feature toggles live in the new `org_settings` table. Defaults
seeded by `scripts/migrate_v13_spec.py`. SUPER_ADMIN edits via
`/app/super-admin/settings`. Keys: `mcq_attendance_enabled`,
`mcq_threshold`, `mcq_window_seconds`, `assignment_nudge_hours`,
`poll_window_seconds`.

Decisions baked into v13:
- **DM-only delivery** for polls + MCQs — no class Telegram group binding.
- **Filesystem storage** for course materials (matches `assignments.body_file_path`).
- **Gap-fill scope** — no architectural refactor; existing handlers untouched.

End-to-end smoke: `bash scripts/demo_v13.sh` (after seed + migrations).

### Telegram (optional)
```bash
# 1. Create a bot via @BotFather, copy the HTTP token
# 2. Set in .env:
#       TELEGRAM_BOT_TOKEN=123456:ABC...
#       TELEGRAM_BOT_USERNAME=samscheduler_bot   # @-less, used to build deep links
# 3. Run migration v9, then:
docker compose up -d telegram telegram_queue_worker
#       OR for host-side dev:
python -m src.services.telegram_poller
# 4. Web UI → /app/settings → Telegram tab → Connect → DM the bot /start CODE
```

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
