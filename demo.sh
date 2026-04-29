#!/usr/bin/env bash
# demo.sh — single entry point for the S.A.M prototype demo.
#
# Subcommands:
#   ./demo.sh up               start stack, wait healthy, migrate, seed
#   ./demo.sh reset            same as `up` but drops the DB volume first
#   ./demo.sh status           one-page green/red health board
#   ./demo.sh logs             tail -f the demo-relevant containers
#   ./demo.sh stage-meeting    create a real meeting at NOW+13min (for live 10-min reminder)
#   ./demo.sh down             stop the stack (keeps the volume)
#
# Run from the repo root. Requires docker + curl + jq.

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_BASE="${API_BASE:-http://localhost:8000}"
BACKEND="backend"
DB="db"
COMPOSE="${COMPOSE:-docker compose}"

# Migrations in order. New migrations append to the end.
MIGRATIONS=(
  scripts/init_meetings_tables.py
  scripts/migrate_v3_features.py
  scripts/migrate_phone_and_student.py
  scripts/migrate_v4_foundations.py
  scripts/migrate_v5_timetable.py
  scripts/migrate_v6_academic_calendar.py
  scripts/migrate_v7_tasks.py
  scripts/migrate_v8_booking_briefing.py
  scripts/migrate_v9_telegram.py
  scripts/migrate_v10_demo.py
)

# Demo-relevant containers tailed by `./demo.sh logs`.
DEMO_CONTAINERS=(backend telegram telegram_queue_worker beat worker)

# Colors (only when stdout is a TTY).
if [[ -t 1 ]]; then
  C_GREEN=$'\033[32m'; C_RED=$'\033[31m'; C_YELLOW=$'\033[33m'
  C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'; C_RESET=$'\033[0m'
else
  C_GREEN=""; C_RED=""; C_YELLOW=""; C_BOLD=""; C_DIM=""; C_RESET=""
fi

OK="${C_GREEN}✓${C_RESET}"
FAIL="${C_RED}✗${C_RESET}"
WARN="${C_YELLOW}!${C_RESET}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { printf "%s%s%s\n" "${C_BOLD}" "$*" "${C_RESET}"; }
note() { printf "%s%s%s\n" "${C_DIM}" "$*" "${C_RESET}"; }
err()  { printf "%s[demo] %s%s\n" "${C_RED}" "$*" "${C_RESET}" >&2; }

require() {
  command -v "$1" >/dev/null 2>&1 || { err "missing dependency: $1"; exit 1; }
}

# Wait for a command to succeed, polling every $interval seconds for up to
# $timeout seconds. Echoes a single dot per attempt.
wait_for() {
  local label="$1" timeout="$2" interval="$3"; shift 3
  local elapsed=0
  printf "  waiting for %s " "${label}"
  while (( elapsed < timeout )); do
    if "$@" >/dev/null 2>&1; then
      printf " %s\n" "${OK}"
      return 0
    fi
    printf "."
    sleep "${interval}"
    elapsed=$((elapsed + interval))
  done
  printf " %s\n" "${FAIL}"
  return 1
}

ensure_token() {
  if ! grep -q "^TELEGRAM_BOT_TOKEN=." .env 2>/dev/null; then
    err "TELEGRAM_BOT_TOKEN missing from .env — bot won't start"
    err "add the token from @BotFather and re-run"
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

cmd_up() {
  ensure_token
  log "[1/5] docker compose up -d --build"
  ${COMPOSE} up -d --build

  log "[2/5] waiting for postgres + backend"
  wait_for "postgres" 60 2 ${COMPOSE} exec -T ${DB} pg_isready -U postgres
  wait_for "backend"  60 2 curl -fsS "${API_BASE}/" -o /dev/null

  log "[3/5] running migrations"
  for f in "${MIGRATIONS[@]}"; do
    printf "  %s ... " "${f}"
    if ${COMPOSE} exec -T ${BACKEND} python "${f}" >/dev/null 2>&1; then
      printf "%s\n" "${OK}"
    else
      printf "%s\n" "${FAIL}"
      err "migration ${f} failed — see: ${COMPOSE} exec ${BACKEND} python ${f}"
      exit 1
    fi
  done

  log "[4/5] seeding demo cast"
  ${COMPOSE} exec -T -e DEMO_SPOC_TG_CHAT_ID="${DEMO_SPOC_TG_CHAT_ID:-}" \
                  -e DEMO_RIYA_TG_CHAT_ID="${DEMO_RIYA_TG_CHAT_ID:-}" \
                  ${BACKEND} python scripts/seed_demo.py

  log "[5/5] verifying Telegram bot token"
  if check_bot >/dev/null 2>&1; then
    local handle; handle=$(check_bot)
    printf "  %s bot reachable: ${C_BOLD}@%s${C_RESET}\n" "${OK}" "${handle}"
  else
    printf "  %s bot token rejected by Telegram — fix TELEGRAM_BOT_TOKEN in .env\n" "${FAIL}"
  fi

  echo
  cmd_status
  echo
  log "ready. open:"
  note "  http://localhost:3000      (web app)"
  note "  http://localhost:8000/docs (API docs)"
  note "  Telegram: @samforge_bot"
}

cmd_reset() {
  log "destroying postgres volume + restarting"
  ${COMPOSE} down -v
  cmd_up
}

cmd_down() {
  log "stopping stack (keeping data volume)"
  ${COMPOSE} down
}

# Returns the bot's @handle if the token works, else exits non-zero.
check_bot() {
  local token; token=$(grep '^TELEGRAM_BOT_TOKEN=' .env | head -1 | cut -d= -f2-)
  [[ -n "${token}" ]] || return 1
  local resp; resp=$(curl -fsS "https://api.telegram.org/bot${token}/getMe" 2>/dev/null) || return 1
  local handle; handle=$(printf '%s' "${resp}" | jq -r '.result.username // empty' 2>/dev/null) || return 1
  [[ -n "${handle}" ]] || return 1
  printf '%s\n' "${handle}"
}

cmd_status() {
  log "service health"

  # Postgres
  if ${COMPOSE} exec -T ${DB} pg_isready -U postgres >/dev/null 2>&1; then
    printf "  %s postgres reachable\n" "${OK}"
  else
    printf "  %s postgres unreachable\n" "${FAIL}"
  fi

  # Redis
  if ${COMPOSE} exec -T redis redis-cli ping >/dev/null 2>&1; then
    printf "  %s redis reachable\n" "${OK}"
  else
    printf "  %s redis unreachable\n" "${FAIL}"
  fi

  # Backend
  if curl -fsS "${API_BASE}/" >/dev/null 2>&1; then
    printf "  %s backend %s\n" "${OK}" "${API_BASE}"
  else
    printf "  %s backend %s unreachable\n" "${FAIL}" "${API_BASE}"
  fi

  # Telegram poller — running and recent log activity?
  if ${COMPOSE} ps telegram 2>/dev/null | grep -qE "Up|running"; then
    if ${COMPOSE} logs --since 30s --tail 50 telegram 2>/dev/null \
         | grep -qE "poller started|getUpdates|update_id"; then
      printf "  %s telegram poller active\n" "${OK}"
    else
      printf "  %s telegram poller running but no recent activity\n" "${WARN}"
    fi
  else
    printf "  %s telegram poller not running\n" "${FAIL}"
  fi

  # Beat
  if ${COMPOSE} ps beat 2>/dev/null | grep -qE "Up|running"; then
    if ${COMPOSE} logs --since 6m --tail 50 beat 2>/dev/null \
         | grep -qE "tick_user_briefings|Sending due task"; then
      printf "  %s beat ticking\n" "${OK}"
    else
      printf "  %s beat running but no recent ticks (5min cadence)\n" "${WARN}"
    fi
  else
    printf "  %s beat not running\n" "${FAIL}"
  fi

  # Bot token
  if handle=$(check_bot 2>/dev/null); then
    printf "  %s bot @%s\n" "${OK}" "${handle}"
  else
    printf "  %s bot token rejected\n" "${FAIL}"
  fi

  # Demo cast loaded?
  log "demo cast"
  ${COMPOSE} exec -T ${DB} psql -U postgres -d sam -t -c "
    SELECT format('  %s %s — %s', role, full_name,
                  CASE WHEN telegram_chat_id IS NULL THEN 'unpaired'
                       ELSE 'tg:' || telegram_chat_id END)
      FROM users WHERE email LIKE '%@example.edu' ORDER BY id;
  " 2>/dev/null | sed '/^$/d' || printf "  %s could not query demo cast\n" "${FAIL}"
}

cmd_logs() {
  log "tailing ${DEMO_CONTAINERS[*]} (Ctrl-C to stop)"
  ${COMPOSE} logs -f --tail=20 "${DEMO_CONTAINERS[@]}"
}

cmd_stage_meeting() {
  ensure_token
  log "scheduling a real demo meeting at NOW+13min"
  note "Dr Sharma + Prof Kumar will get the broadcast immediately."
  note "The 10-min Celery reminder fires at NOW+3min — set a timer."

  ${COMPOSE} exec -T ${BACKEND} python scripts/stage_demo_meeting.py "$@"
}

usage() {
  cat <<EOF
S.A.M demo orchestrator

Usage:
  ./demo.sh <command> [args...]

Commands:
  up                Start stack, wait healthy, run all migrations, seed demo cast
  reset             Same as 'up' but drops the postgres volume first (full reset)
  status            One-page green/red health board
  logs              tail -f backend, telegram, queue worker, beat, worker
  stage-meeting     Create a real meeting at NOW+13min so the 10-min reminder
                    fires live on stage. Pass extra args through to the helper:
                      ./demo.sh stage-meeting --title "Exam review prep"
                      ./demo.sh stage-meeting --offset-min 8     (override timing)
                      ./demo.sh stage-meeting --no-calendar      (skip Google write)
  down              Stop the stack (keeps the data volume — resume with 'up')

Env overrides:
  DEMO_SPOC_TG_CHAT_ID   pre-pair the SPOC's Telegram during seed
  DEMO_RIYA_TG_CHAT_ID   pre-pair the student persona (default: leave unpaired)
  API_BASE               default http://localhost:8000
  COMPOSE                default 'docker compose'

Examples:
  DEMO_SPOC_TG_CHAT_ID=123456789 ./demo.sh up
  ./demo.sh status
  ./demo.sh stage-meeting
  ./demo.sh logs
EOF
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

require docker
require curl
require jq

cmd="${1:-}"
shift || true

case "${cmd}" in
  up)             cmd_up "$@" ;;
  reset)          cmd_reset "$@" ;;
  status)         cmd_status "$@" ;;
  logs)           cmd_logs "$@" ;;
  stage-meeting|meeting)
                  cmd_stage_meeting "$@" ;;
  down)           cmd_down "$@" ;;
  ""|-h|--help|help)  usage ;;
  *)              err "unknown command: ${cmd}"; usage; exit 2 ;;
esac
