# Graph Report - .  (2026-04-29)

## Corpus Check
- 189 files · ~60,922 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1196 nodes · 2160 edges · 94 communities detected
- Extraction: 61% EXTRACTED · 39% INFERRED · 0% AMBIGUOUS · INFERRED: 832 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Admin & RBAC Routes|Admin & RBAC Routes]]
- [[_COMMUNITY_Meeting Analytics & Availability|Meeting Analytics & Availability]]
- [[_COMMUNITY_LLM Processor & Clarifications|LLM Processor & Clarifications]]
- [[_COMMUNITY_Calendar Sync & Session Cache|Calendar Sync & Session Cache]]
- [[_COMMUNITY_Email Templates & Infra Config|Email Templates & Infra Config]]
- [[_COMMUNITY_API Route Tests|API Route Tests]]
- [[_COMMUNITY_DB Pool & User CRUD|DB Pool & User CRUD]]
- [[_COMMUNITY_Academic Calendar Events|Academic Calendar Events]]
- [[_COMMUNITY_Pydantic Models & Email Service|Pydantic Models & Email Service]]
- [[_COMMUNITY_Distributed Locking & ICS|Distributed Locking & ICS]]
- [[_COMMUNITY_Project Architecture & Conventions|Project Architecture & Conventions]]
- [[_COMMUNITY_Broadcast & User Groups|Broadcast & User Groups]]
- [[_COMMUNITY_Frontend Auth Client|Frontend Auth Client]]
- [[_COMMUNITY_Health Check Probes|Health Check Probes]]
- [[_COMMUNITY_Phase Roadmap Concepts|Phase Roadmap Concepts]]
- [[_COMMUNITY_Google OAuth Service|Google OAuth Service]]
- [[_COMMUNITY_Multimodal Ingest (OCRWhisper)|Multimodal Ingest (OCR/Whisper)]]
- [[_COMMUNITY_Faculty Name Resolver|Faculty Name Resolver]]
- [[_COMMUNITY_Date Parser Utilities|Date Parser Utilities]]
- [[_COMMUNITY_Meeting State Machine Tests|Meeting State Machine Tests]]
- [[_COMMUNITY_Role-Based Access Control|Role-Based Access Control]]
- [[_COMMUNITY_WhatsApp Button Orchestration|WhatsApp Button Orchestration]]
- [[_COMMUNITY_DB Migrations v4-v8|DB Migrations v4-v8]]
- [[_COMMUNITY_OAuth Status Pill UI|OAuth Status Pill UI]]
- [[_COMMUNITY_PowerShell venv Activation|PowerShell venv Activation]]
- [[_COMMUNITY_Login Hero Component|Login Hero Component]]
- [[_COMMUNITY_Chat Panel UI|Chat Panel UI]]
- [[_COMMUNITY_Frontend Architecture Notes|Frontend Architecture Notes]]
- [[_COMMUNITY_Connect Google Button|Connect Google Button]]
- [[_COMMUNITY_Login Sign-In Card|Login Sign-In Card]]
- [[_COMMUNITY_Agenda Strip Component|Agenda Strip Component]]
- [[_COMMUNITY_useAgenda Hook|useAgenda Hook]]
- [[_COMMUNITY_FastAPI App Entrypoint|FastAPI App Entrypoint]]
- [[_COMMUNITY_DB Operations Guidelines|DB Operations Guidelines]]
- [[_COMMUNITY_Environment Configuration|Environment Configuration]]
- [[_COMMUNITY_Root Layout|Root Layout]]
- [[_COMMUNITY_Not-Found Page|Not-Found Page]]
- [[_COMMUNITY_Providers & Toaster|Providers & Toaster]]
- [[_COMMUNITY_Chat Home Page|Chat Home Page]]
- [[_COMMUNITY_Broadcasts Page|Broadcasts Page]]
- [[_COMMUNITY_Faculty Page|Faculty Page]]
- [[_COMMUNITY_Groups Page|Groups Page]]
- [[_COMMUNITY_Meetings Page|Meetings Page]]
- [[_COMMUNITY_Composer Component|Composer Component]]
- [[_COMMUNITY_Message Bubble Component|Message Bubble Component]]
- [[_COMMUNITY_File Drop Zone|File Drop Zone]]
- [[_COMMUNITY_Loading Dots|Loading Dots]]
- [[_COMMUNITY_Sidebar Navigation|Sidebar Navigation]]
- [[_COMMUNITY_Badge Primitive|Badge Primitive]]
- [[_COMMUNITY_Separator Primitive|Separator Primitive]]
- [[_COMMUNITY_Skeleton Primitive|Skeleton Primitive]]
- [[_COMMUNITY_Class-Name Util|Class-Name Util]]
- [[_COMMUNITY_Notifications WebSocket|Notifications WebSocket]]
- [[_COMMUNITY_ICS Generator Test|ICS Generator Test]]
- [[_COMMUNITY_Testing Guidelines|Testing Guidelines]]
- [[_COMMUNITY_Naming Conventions|Naming Conventions]]
- [[_COMMUNITY_Next Env Types|Next Env Types]]
- [[_COMMUNITY_Next Config|Next Config]]
- [[_COMMUNITY_PostCSS Config|PostCSS Config]]
- [[_COMMUNITY_Tailwind Config|Tailwind Config]]
- [[_COMMUNITY_Settings Page|Settings Page]]
- [[_COMMUNITY_Login Page|Login Page]]
- [[_COMMUNITY_Empty State Component|Empty State Component]]
- [[_COMMUNITY_Header Component|Header Component]]
- [[_COMMUNITY_Button Primitive|Button Primitive]]
- [[_COMMUNITY_Card Primitive|Card Primitive]]
- [[_COMMUNITY_Input Primitive|Input Primitive]]
- [[_COMMUNITY_Frontend Types|Frontend Types]]
- [[_COMMUNITY_Greenlet Header|Greenlet Header]]
- [[_COMMUNITY_Reset DB Script|Reset DB Script]]
- [[_COMMUNITY_Init __init__|Init __init__]]
- [[_COMMUNITY_Init __init__|Init __init__]]
- [[_COMMUNITY_Init __init__|Init __init__]]
- [[_COMMUNITY_Init __init__|Init __init__]]
- [[_COMMUNITY_Init __init__|Init __init__]]
- [[_COMMUNITY_Availability Test|Availability Test]]
- [[_COMMUNITY_Test Scenario Busy|Test Scenario: Busy]]
- [[_COMMUNITY_Test Scenario Free|Test Scenario: Free]]
- [[_COMMUNITY_Test Scenario Network Error|Test Scenario: Network Error]]
- [[_COMMUNITY_Resolver Test|Resolver Test]]
- [[_COMMUNITY_WhatsApp Audit Test|WhatsApp Audit Test]]
- [[_COMMUNITY_Running the App|Running the App]]
- [[_COMMUNITY_Import Organization|Import Organization]]
- [[_COMMUNITY_Type Hints Guideline|Type Hints Guideline]]
- [[_COMMUNITY_Docstring Guideline|Docstring Guideline]]
- [[_COMMUNITY_Performance Notes|Performance Notes]]
- [[_COMMUNITY_API Integration Notes|API Integration Notes]]
- [[_COMMUNITY_Development Workflow|Development Workflow]]
- [[_COMMUNITY_Testing Targets|Testing Targets]]
- [[_COMMUNITY_License Note|License Note]]
- [[_COMMUNITY_python-dotenv Dep|python-dotenv Dep]]
- [[_COMMUNITY_Jinja2 Dep|Jinja2 Dep]]
- [[_COMMUNITY_Phase 1 Stack|Phase 1 Stack]]
- [[_COMMUNITY_Phase 4 Stack|Phase 4 Stack]]

## God Nodes (most connected - your core abstractions)
1. `Config` - 92 edges
2. `get_db_connection()` - 67 edges
3. `release_db_connection()` - 67 edges
4. `_hdr()` - 37 edges
5. `LLMProcessor` - 28 edges
6. `route_intent()` - 27 edges
7. `_handle_document()` - 22 edges
8. `_handle_text()` - 21 edges
9. `queue_whatsapp()` - 20 edges
10. `create_meeting()` - 17 edges

## Surprising Connections (you probably didn't know these)
- `End-to-end HTTP tests for every S.A.M API route.  Strategy: drive the FastAPI ap` --uses--> `Config`  [INFERRED]
  tests/test_api_endpoints.py → src/utils/config_loader.py
- `S.A.M Project Overview` --semantically_similar_to--> `S.A.M Backend (faculty-scheduling platform)`  [INFERRED] [semantically similar]
  AGENTS.md → README.md
- `Service Function Pattern (validate, resolve, act, return)` --semantically_similar_to--> `Worker protocol envelope {success, data, message, error_code}`  [INFERRED] [semantically similar]
  AGENTS.md → README.md
- `DatabaseInitializationError` --uses--> `Config`  [INFERRED]
  scripts/init_meetings_tables.py → src/utils/config_loader.py
- `Idempotent migration:   - add users.phone_number (unique when present)   - add u` --uses--> `Config`  [INFERRED]
  scripts/migrate_phone_and_student.py → src/utils/config_loader.py

## Hyperedges (group relationships)
- **SPOC intent execution pipeline (NL -> resolve -> conflict -> calendar -> notify)** — readme_route_natural_language, readme_faculty_resolution, readme_conflict_aware_scheduling, readme_calendar_writes, readme_multi_channel_notifications [EXTRACTED 0.95]
- **v4-v8 release: migrations, beat scheduler, role gating** — next_migration_v4_foundations, next_migration_v5_timetable, next_migration_v6_academic_calendar, next_migration_v7_tasks, next_migration_v8_booking_briefing, next_celery_beat_container [EXTRACTED 0.95]
- **File ingestion stack (rosters, timetables, tasks, audio)** — requirements_file_ingestion, requirements_pytesseract, requirements_faster_whisper, readme_route_uploads_groups, next_admin_tasks_upload_flow [INFERRED 0.85]
- **Brain-Code Architecture pattern (cognitive + deterministic + failsafe)** — samv2_layer_brain, samv2_layer_code, samv2_failsafe_design, samv2_smart_conflict_detector [EXTRACTED 1.00]
- **v2.0 Phase 3 cross-team task allocation** — phase3_aniket_oauth_engine, phase3_krishna_schema, phase3_bismun_join_org, phase3_kishan_calendar, phase3_mayank_state_machine, phase3_ayush_llm_processor [EXTRACTED 1.00]
- **Defense-in-depth security control stack** — security_fernet_encryption, security_pydantic_validation, security_rls_policies, security_jwt_httponly_cookies, security_rate_limiting [EXTRACTED 1.00]

## Communities

### Community 0 - "Admin & RBAC Routes"
Cohesion: 0.03
Nodes (119): is_blocked(), Return the academic_event blocking `when` (HOLIDAY or EXAM only — BREAK     and, list_users(), patch_user(), SUPER_ADMIN user management.  Routes:     GET   /api/v1/admin/users     PATCH /a, UserPatch, approve_booking(), _decide() (+111 more)

### Community 1 - "Meeting Analytics & Availability"
Cohesion: 0.03
Nodes (87): api_meeting_analytics(), analytics.py ------------ Feature 10: Meeting analytics endpoint.  GET /api/v1/a, Return aggregated meeting statistics for a user over a date range.      Response, api_get_availability(), calculate_free_slots(), _filter_by_working_hours(), find_common_slots(), availability_engine.py ---------------------- Calculates free time slots for one (+79 more)

### Community 2 - "LLM Processor & Clarifications"
Cohesion: 0.03
Nodes (63): get_clarification(), Generates targeted clarification questions for missing meeting details., Config, Central configuration class.     Access variables like: Config.GOOGLE_CLIENT_ID, LLMProcessor, Cognitive engine of S.A.M.     Translates natural-language user inputs into stru, Idempotent migration:   - add users.phone_number (unique when present)   - add u, Idempotent migration v3: saved groups + WhatsApp audit log.  Run after migrate_p (+55 more)

### Community 3 - "Calendar Sync & Session Cache"
Cohesion: 0.05
Nodes (76): upload_calendar(), already_seen(), append_history(), clear_session(), _client(), get_session(), _key(), _norm() (+68 more)

### Community 4 - "Email Templates & Infra Config"
Cohesion: 0.03
Nodes (87): Email Cancel HTML Template, Email Invite HTML Template, Jinja2 template variables (title, time_str, location, organizer, agenda), Email Update HTML Template, DB_HOST=db (not localhost) for inter-container networking, .env Configuration Vector (DB_HOST=db, REDIS_URL, SECRET_KEY), Frontend decoupled from container network for HMR, S.A.M. Infrastructure Instantiation Protocol v2.1 (+79 more)

### Community 5 - "API Route Tests"
Cohesion: 0.05
Nodes (18): delete(), delete_event(), _hdr(), _jwt(), End-to-end HTTP tests for every S.A.M API route.  Strategy: drive the FastAPI ap, _sign(), TestAgendaRoute, TestAuthRoutes (+10 more)

### Community 6 - "DB Pool & User CRUD"
Cohesion: 0.05
Nodes (55): create_user(), get_db(), get_pool(), get_system_db(), get_user_by_email(), get_user_by_phone(), init_connection_pool(), log_audit_action() (+47 more)

### Community 7 - "Academic Calendar Events"
Cohesion: 0.05
Nodes (41): AcademicEventIn, block_message(), _coerce_date(), _coerce_kind(), confirm_calendar(), extract_events_from_text(), get_events(), import_events() (+33 more)

### Community 8 - "Pydantic Models & Email Service"
Cohesion: 0.05
Nodes (43): AvailabilityRequest, WorkingHours, BaseModel, CalendarSyncRequest, DirectEmailService, direct_email_service.py ----------------------- Send emails directly to faculty, Resolve a faculty member's name to an email address and send them an email., api_queue_email() (+35 more)

### Community 9 - "Distributed Locking & ICS"
Cohesion: 0.05
Nodes (40): distributed_lock(), DoubleBookingError, Raised when the resource is locked by another user., Acquires a distributed lock asynchronously.     NON-BLOCKING: Allows other users, Exception, generate_ics(), Generate an ICS file for a meeting.      Args:         title (str): Meeting titl, create_tables() (+32 more)

### Community 10 - "Project Architecture & Conventions"
Cohesion: 0.04
Nodes (54): check_scheduler_conflict (conflict detection function), Error Handling Pattern (fail-safe defaults), Project Structure (src/api, services, utils, templates), S.A.M Project Overview, Security Notes (no secrets in logs, parameterized queries), Service Function Pattern (validate, resolve, act, return), Technology Stack (Python 3.10+, Gemini, Postgres, Click), Faculty name disambiguation threshold (6 pts) (+46 more)

### Community 11 - "Broadcast & User Groups"
Cohesion: 0.06
Nodes (36): broadcast_by_filters(), broadcast_to_attendees(), _fetch_users(), broadcast_service.py -------------------- Fan-out a message to many stakeholders, Resolve recipients by group membership (preferred when given) or by     role/dep, _send_one(), add_member(), add_members_by_email() (+28 more)

### Community 12 - "Frontend Auth Client"
Cohesion: 0.06
Nodes (21): ApiError, apiFetch(), clearToken(), decodeJwt(), getToken(), getUser(), isExpired(), AppLayout() (+13 more)

### Community 13 - "Health Check Probes"
Cohesion: 0.16
Nodes (21): api_health(), _broken(), check_all(), _live(), _probe_database_sync(), _probe_google_oauth(), _probe_llm_nvidia(), _probe_redis_sync() (+13 more)

### Community 14 - "Phase Roadmap Concepts"
Cohesion: 0.13
Nodes (16): Admin task ingestion (sheet/PDF/voice memo), Booking authority approval queue, Celery beat container (5min tick_user_briefings), Class cancellation broadcast flow, Class enrolment requires user_groups row matching batch, Daily briefing scheduled tick, Faculty WhatsApp timetable upload flow, OCR on phone-camera timetables is lossy (rationale: editable grid as safety net) (+8 more)

### Community 15 - "Google OAuth Service"
Cohesion: 0.18
Nodes (8): auth_callback(), get_login_url(), LoginRequest, Returns the Google OAuth login URL.     The frontend redirects the user to this, Handles the OAuth callback from the frontend.      Flow:     1. Exchange the tem, create_jwt_token(), GoogleAuthService, Create a signed JWT with user_id, org_id, and role claims.     The frontend stor

### Community 16 - "Multimodal Ingest (OCR/Whisper)"
Cohesion: 0.18
Nodes (13): _get_whisper_model(), ocr_image(), _preprocess_image(), Local multimodal ingest: image OCR (Tesseract) + audio transcription (faster-whi, Mild preprocessing for phone-camera timetables: grayscale + adaptive     thresho, OCR an image to text. Returns:         {"text": str, "ocr_confidence": Optional[, Lazy-load the faster-whisper model the first time it's needed. Loading     `smal, Force model load at boot so the first user request is fast. (+5 more)

### Community 17 - "Faculty Name Resolver"
Cohesion: 0.24
Nodes (8): _get_cached_faculty(), invalidate_faculty_cache(), user_resolver.py ---------------- Resolve human-readable display names to DB fac, Clear the in-memory faculty cache so the next call re-fetches from DB., Fuzzy-match a name string against the faculty list.      Parameters     --------, Resolve a list of display names to faculty dicts. For each match we also     enr, resolve_faculty_member(), resolve_participants()

### Community 18 - "Date Parser Utilities"
Cohesion: 0.25
Nodes (7): calculate_end_time(), format_for_google(), parse_iso_from_llm(), iss file kee need kishan bhai koo pta hai kyu hai peechli baar dates koo handle, Validates and converts the date string received from Gemini API.          Why th, Calculates the meeting end time.     Required because Google Calendar needs both, Final step: Converts the python object to the strict string Google API demands.

### Community 19 - "Meeting State Machine Tests"
Cohesion: 0.25
Nodes (0): 

### Community 20 - "Role-Based Access Control"
Cohesion: 0.33
Nodes (5): has_role(), Role-based access control for FastAPI routes.  The JWT middleware (src/utils/mid, Build a FastAPI dependency that allows only the given roles.      SUPER_ADMIN al, Convenience predicate for inline checks (not for dependency injection)., require_roles()

### Community 21 - "WhatsApp Button Orchestration"
Cohesion: 0.47
Nodes (2): Confirm the orchestrator routes Meta button_reply payloads through to the right, TestButtonOrchestration

### Community 22 - "DB Migrations v4-v8"
Cohesion: 0.33
Nodes (6): migrate_v4_foundations, migrate_v5_timetable, migrate_v6_academic_calendar, migrate_v7_tasks, migrate_v8_booking_briefing, v4-v8 Release Summary (5 migrations, 17 services, 8 routes, 5 pages)

### Community 23 - "OAuth Status Pill UI"
Cohesion: 0.4
Nodes (2): OAuthStatusPill(), useGoogleStatus()

### Community 24 - "PowerShell venv Activation"
Cohesion: 0.4
Nodes (0): 

### Community 25 - "Login Hero Component"
Cohesion: 0.5
Nodes (0): 

### Community 26 - "Chat Panel UI"
Cohesion: 0.83
Nodes (3): formatResult(), handleSubmit(), uid()

### Community 27 - "Frontend Architecture Notes"
Cohesion: 0.5
Nodes (4): Next.js 14 SPOC Dashboard (frontend/), Frontend runs natively (rationale: NTFS bind-mount breaks Next.js cache), JWT in localStorage (sam_jwt) attached as Bearer, OAuth status pill polls /me/google-status

### Community 28 - "Connect Google Button"
Cohesion: 0.67
Nodes (0): 

### Community 29 - "Login Sign-In Card"
Cohesion: 0.67
Nodes (0): 

### Community 30 - "Agenda Strip Component"
Cohesion: 0.67
Nodes (0): 

### Community 31 - "useAgenda Hook"
Cohesion: 1.0
Nodes (2): todayIso(), useAgenda()

### Community 32 - "FastAPI App Entrypoint"
Cohesion: 0.67
Nodes (0): 

### Community 33 - "DB Operations Guidelines"
Cohesion: 0.67
Nodes (3): Database Management Scripts (init, seed, reset), Database Operations Guideline, Database Transaction Pattern (commit/rollback/close)

### Community 34 - "Environment Configuration"
Cohesion: 0.67
Nodes (3): Configuration Management (env vars, config_loader), Environment Variables (.env keys), Setup (Docker Compose recommended)

### Community 35 - "Root Layout"
Cohesion: 1.0
Nodes (0): 

### Community 36 - "Not-Found Page"
Cohesion: 1.0
Nodes (0): 

### Community 37 - "Providers & Toaster"
Cohesion: 1.0
Nodes (0): 

### Community 38 - "Chat Home Page"
Cohesion: 1.0
Nodes (0): 

### Community 39 - "Broadcasts Page"
Cohesion: 1.0
Nodes (0): 

### Community 40 - "Faculty Page"
Cohesion: 1.0
Nodes (0): 

### Community 41 - "Groups Page"
Cohesion: 1.0
Nodes (0): 

### Community 42 - "Meetings Page"
Cohesion: 1.0
Nodes (0): 

### Community 43 - "Composer Component"
Cohesion: 1.0
Nodes (0): 

### Community 44 - "Message Bubble Component"
Cohesion: 1.0
Nodes (0): 

### Community 45 - "File Drop Zone"
Cohesion: 1.0
Nodes (0): 

### Community 46 - "Loading Dots"
Cohesion: 1.0
Nodes (0): 

### Community 47 - "Sidebar Navigation"
Cohesion: 1.0
Nodes (0): 

### Community 48 - "Badge Primitive"
Cohesion: 1.0
Nodes (0): 

### Community 49 - "Separator Primitive"
Cohesion: 1.0
Nodes (0): 

### Community 50 - "Skeleton Primitive"
Cohesion: 1.0
Nodes (0): 

### Community 51 - "Class-Name Util"
Cohesion: 1.0
Nodes (0): 

### Community 52 - "Notifications WebSocket"
Cohesion: 1.0
Nodes (0): 

### Community 53 - "ICS Generator Test"
Cohesion: 1.0
Nodes (1): run karne kaa tarika in 1. set PYTHONPATH=. 2. python tests/test_ics_generator.p

### Community 54 - "Testing Guidelines"
Cohesion: 1.0
Nodes (2): Running Tests via unittest, Testing Guidelines (mock externals, TDD)

### Community 55 - "Naming Conventions"
Cohesion: 1.0
Nodes (2): Naming Conventions (snake_case, PascalCase, UPPER_SNAKE_CASE), Repository Layout

### Community 56 - "Next Env Types"
Cohesion: 1.0
Nodes (0): 

### Community 57 - "Next Config"
Cohesion: 1.0
Nodes (0): 

### Community 58 - "PostCSS Config"
Cohesion: 1.0
Nodes (0): 

### Community 59 - "Tailwind Config"
Cohesion: 1.0
Nodes (0): 

### Community 60 - "Settings Page"
Cohesion: 1.0
Nodes (0): 

### Community 61 - "Login Page"
Cohesion: 1.0
Nodes (0): 

### Community 62 - "Empty State Component"
Cohesion: 1.0
Nodes (0): 

### Community 63 - "Header Component"
Cohesion: 1.0
Nodes (0): 

### Community 64 - "Button Primitive"
Cohesion: 1.0
Nodes (0): 

### Community 65 - "Card Primitive"
Cohesion: 1.0
Nodes (0): 

### Community 66 - "Input Primitive"
Cohesion: 1.0
Nodes (0): 

### Community 67 - "Frontend Types"
Cohesion: 1.0
Nodes (0): 

### Community 68 - "Greenlet Header"
Cohesion: 1.0
Nodes (0): 

### Community 69 - "Reset DB Script"
Cohesion: 1.0
Nodes (0): 

### Community 70 - "Init __init__"
Cohesion: 1.0
Nodes (0): 

### Community 71 - "Init __init__"
Cohesion: 1.0
Nodes (0): 

### Community 72 - "Init __init__"
Cohesion: 1.0
Nodes (0): 

### Community 73 - "Init __init__"
Cohesion: 1.0
Nodes (0): 

### Community 74 - "Init __init__"
Cohesion: 1.0
Nodes (0): 

### Community 75 - "Availability Test"
Cohesion: 1.0
Nodes (0): 

### Community 76 - "Test Scenario: Busy"
Cohesion: 1.0
Nodes (1): Scenario: The API returns a list of events (User is BUSY).         Expected: Ret

### Community 77 - "Test Scenario: Free"
Cohesion: 1.0
Nodes (1): Scenario: The API returns an empty list (User is FREE).         Expected: Return

### Community 78 - "Test Scenario: Network Error"
Cohesion: 1.0
Nodes (1): Scenario: Google API raises an exception (e.g., Network Error).         Expected

### Community 79 - "Resolver Test"
Cohesion: 1.0
Nodes (0): 

### Community 80 - "WhatsApp Audit Test"
Cohesion: 1.0
Nodes (0): 

### Community 81 - "Running the App"
Cohesion: 1.0
Nodes (1): Running the Application

### Community 82 - "Import Organization"
Cohesion: 1.0
Nodes (1): Import Organization (absolute imports, grouped)

### Community 83 - "Type Hints Guideline"
Cohesion: 1.0
Nodes (1): Type Hints Guideline

### Community 84 - "Docstring Guideline"
Cohesion: 1.0
Nodes (1): Function Documentation (docstrings)

### Community 85 - "Performance Notes"
Cohesion: 1.0
Nodes (1): Performance Notes (caching, indexes, rate limits)

### Community 86 - "API Integration Notes"
Cohesion: 1.0
Nodes (1): API Integration Notes (retries, fallbacks)

### Community 87 - "Development Workflow"
Cohesion: 1.0
Nodes (1): Development Workflow (TDD, run tests frequently)

### Community 88 - "Testing Targets"
Cohesion: 1.0
Nodes (1): Testing targets (95% resolution, 90% conflict detection, <3s p95)

### Community 89 - "License Note"
Cohesion: 1.0
Nodes (1): License (academic + experimental)

### Community 90 - "python-dotenv Dep"
Cohesion: 1.0
Nodes (1): python-dotenv

### Community 91 - "Jinja2 Dep"
Cohesion: 1.0
Nodes (1): jinja2 (templates)

### Community 92 - "Phase 1 Stack"
Cohesion: 1.0
Nodes (1): Phase 1 stack: Python 3.10+, Gemini, dateparser, SQLite, click

### Community 93 - "Phase 4 Stack"
Cohesion: 1.0
Nodes (1): Phase 4 stack: React 18, Tailwind+shadcn, Django REST, PostgreSQL

## Knowledge Gaps
- **259 isolated node(s):** `Every 5 minutes: dispatch a daily briefing to any user whose     briefing_time f`, `Assemble a short morning briefing string.`, `Force-load the faster-whisper model into worker memory so the first     user-fac`, `Fire whisper warmup once per worker process at boot. Best-effort — if     SAM_SK`, `Queue a 24-hour reminder email + WhatsApp to all meeting participants.     Sched` (+254 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Root Layout`** (2 nodes): `layout.tsx`, `RootLayout()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Not-Found Page`** (2 nodes): `not-found.tsx`, `NotFound()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Providers & Toaster`** (2 nodes): `providers.tsx`, `ClientToaster()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Chat Home Page`** (2 nodes): `page.tsx`, `ChatHomePage()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Broadcasts Page`** (2 nodes): `page.tsx`, `BroadcastsPage()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Faculty Page`** (2 nodes): `page.tsx`, `FacultyPage()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Groups Page`** (2 nodes): `page.tsx`, `GroupsPage()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Meetings Page`** (2 nodes): `page.tsx`, `MeetingsPage()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Composer Component`** (2 nodes): `Composer()`, `Composer.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Message Bubble Component`** (2 nodes): `MessageBubble.tsx`, `MessageBubble()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `File Drop Zone`** (2 nodes): `FileDropZone()`, `FileDropZone.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Loading Dots`** (2 nodes): `LoadingDots.tsx`, `LoadingDots()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Sidebar Navigation`** (2 nodes): `Sidebar.tsx`, `visibleItems()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Badge Primitive`** (2 nodes): `Badge()`, `badge.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Separator Primitive`** (2 nodes): `separator.tsx`, `Separator()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Skeleton Primitive`** (2 nodes): `skeleton.tsx`, `Skeleton()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Class-Name Util`** (2 nodes): `utils.ts`, `cn()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Notifications WebSocket`** (2 nodes): `ws.ts`, `openNotificationsSocket()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `ICS Generator Test`** (2 nodes): `run karne kaa tarika in 1. set PYTHONPATH=. 2. python tests/test_ics_generator.p`, `test_ics_generator.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Testing Guidelines`** (2 nodes): `Running Tests via unittest`, `Testing Guidelines (mock externals, TDD)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Naming Conventions`** (2 nodes): `Naming Conventions (snake_case, PascalCase, UPPER_SNAKE_CASE)`, `Repository Layout`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Next Env Types`** (1 nodes): `next-env.d.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Next Config`** (1 nodes): `next.config.mjs`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `PostCSS Config`** (1 nodes): `postcss.config.mjs`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Tailwind Config`** (1 nodes): `tailwind.config.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Settings Page`** (1 nodes): `page.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Login Page`** (1 nodes): `page.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Empty State Component`** (1 nodes): `EmptyState.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Header Component`** (1 nodes): `Header.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Button Primitive`** (1 nodes): `button.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Card Primitive`** (1 nodes): `card.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Input Primitive`** (1 nodes): `input.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Frontend Types`** (1 nodes): `types.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Greenlet Header`** (1 nodes): `greenlet.h`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Reset DB Script`** (1 nodes): `reset_db.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init __init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init __init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init __init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init __init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init __init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Availability Test`** (1 nodes): `test_availibility.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Test Scenario: Busy`** (1 nodes): `Scenario: The API returns a list of events (User is BUSY).         Expected: Ret`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Test Scenario: Free`** (1 nodes): `Scenario: The API returns an empty list (User is FREE).         Expected: Return`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Test Scenario: Network Error`** (1 nodes): `Scenario: Google API raises an exception (e.g., Network Error).         Expected`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Resolver Test`** (1 nodes): `test_resolver.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `WhatsApp Audit Test`** (1 nodes): `test_whatsapp_audit.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Running the App`** (1 nodes): `Running the Application`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Import Organization`** (1 nodes): `Import Organization (absolute imports, grouped)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Type Hints Guideline`** (1 nodes): `Type Hints Guideline`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Docstring Guideline`** (1 nodes): `Function Documentation (docstrings)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Performance Notes`** (1 nodes): `Performance Notes (caching, indexes, rate limits)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `API Integration Notes`** (1 nodes): `API Integration Notes (retries, fallbacks)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Development Workflow`** (1 nodes): `Development Workflow (TDD, run tests frequently)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Testing Targets`** (1 nodes): `Testing targets (95% resolution, 90% conflict detection, <3s p95)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `License Note`** (1 nodes): `License (academic + experimental)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `python-dotenv Dep`** (1 nodes): `python-dotenv`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Jinja2 Dep`** (1 nodes): `jinja2 (templates)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Phase 1 Stack`** (1 nodes): `Phase 1 stack: Python 3.10+, Gemini, dateparser, SQLite, click`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Phase 4 Stack`** (1 nodes): `Phase 4 stack: React 18, Tailwind+shadcn, Django REST, PostgreSQL`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Config` connect `LLM Processor & Clarifications` to `Admin & RBAC Routes`, `Meeting Analytics & Availability`, `Calendar Sync & Session Cache`, `API Route Tests`, `DB Pool & User CRUD`, `Academic Calendar Events`, `Pydantic Models & Email Service`, `Distributed Locking & ICS`, `Health Check Probes`, `Google OAuth Service`?**
  _High betweenness centrality (0.110) - this node is a cross-community bridge._
- **Why does `route_intent()` connect `Broadcast & User Groups` to `Admin & RBAC Routes`, `Meeting Analytics & Availability`, `LLM Processor & Clarifications`, `Calendar Sync & Session Cache`, `DB Pool & User CRUD`, `Pydantic Models & Email Service`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Why does `extract_meeting_metadata()` connect `Academic Calendar Events` to `Meeting Analytics & Availability`, `LLM Processor & Clarifications`, `Calendar Sync & Session Cache`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Are the 90 inferred relationships involving `Config` (e.g. with `DatabaseInitializationError` and `Idempotent migration:   - add users.phone_number (unique when present)   - add u`) actually correct?**
  _`Config` has 90 INFERRED edges - model-reasoned connections that need verification._
- **Are the 67 inferred relationships involving `str` (e.g. with `_compose_briefing()` and `upload_calendar()`) actually correct?**
  _`str` has 67 INFERRED edges - model-reasoned connections that need verification._
- **Are the 62 inferred relationships involving `get_db_connection()` (e.g. with `tick_user_briefings()` and `_send_task_reminder()`) actually correct?**
  _`get_db_connection()` has 62 INFERRED edges - model-reasoned connections that need verification._
- **Are the 62 inferred relationships involving `release_db_connection()` (e.g. with `tick_user_briefings()` and `_send_task_reminder()`) actually correct?**
  _`release_db_connection()` has 62 INFERRED edges - model-reasoned connections that need verification._