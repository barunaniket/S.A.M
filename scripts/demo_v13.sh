#!/usr/bin/env bash
# scripts/demo_v13.sh
# -------------------
# End-to-end checklist runner for the v13 spec ship. Exercises every
# new surface against a freshly seeded stack. Each step expects a
# specific outcome; any deviation should be a fix-before-merge.
#
# This is a SCRIPTED MANUAL TEST — it pauses at each step so you can
# inspect the result before continuing. Pass --auto to skip the prompts.
#
#   bash scripts/demo_v13.sh           # interactive
#   bash scripts/demo_v13.sh --auto    # batch
#
# Prereqs:
#   - docker compose stack up (db, redis, backend, worker, beat, telegram)
#   - frontend running on :3000 (npm run dev in ./frontend)
#   - SPOC + a few students paired via Telegram (run scripts/seed_demo.py
#     and scripts/load_rosters.py first)

set -e

AUTO="${1:-}"
API="${API_BASE:-http://localhost:8000}"
JWT="${SAM_JWT:-}"

step() {
  printf "\n\033[1;36m── Step %s\033[0m  %s\n" "$1" "$2"
  if [[ "$AUTO" != "--auto" ]]; then
    read -r -p "press enter to run "
  fi
}

note() {
  printf "  \033[2m%s\033[0m\n" "$1"
}

require_jwt() {
  if [[ -z "$JWT" ]]; then
    echo "Set SAM_JWT to a faculty/super-admin token before running."
    echo "  export SAM_JWT=\$(curl ... or grab from localStorage.sam_jwt)"
    exit 1
  fi
}

step 0 "Verify stack is up"
docker compose ps | grep -E "backend|worker|beat|db|redis" || true

step 1 "Run migrations through v13 (idempotent)"
python scripts/init_meetings_tables.py
for m in v3_features v4_foundations v5_timetable v6_academic_calendar v7_tasks v8_booking_briefing v9_telegram v10_demo v11_mcq v12_mvp v13_spec; do
  python "scripts/migrate_${m}.py"
done

step 2 "Route-RBAC audit must pass"
python scripts/audit_route_rbac.py

step 3 "Run v13 unit tests"
python -m unittest \
  tests.test_attendance_query \
  tests.test_intent_router_reads \
  tests.test_mcq_generator \
  tests.test_attendance_mcq_bank \
  tests.test_assignment_reminders \
  tests.test_service_contracts \
  -v

require_jwt

step 4 "GET /api/v1/settings (super-admin)"
note "Expect a JSON blob with mcq_attendance_enabled, mcq_threshold, etc."
curl -fsS -H "Authorization: Bearer $JWT" "$API/api/v1/settings" | head -50

step 5 "GET /api/v1/assignments/mine (faculty)"
curl -fsS -H "Authorization: Bearer $JWT" "$API/api/v1/assignments/mine"

step 6 "GET /api/v1/attendance?subject=DSA&date=$(date +%F) (faculty)"
note "Expect either a present/absent breakdown or an empty data payload."
curl -fsS -H "Authorization: Bearer $JWT" \
  "$API/api/v1/attendance?subject=DSA&date=$(date +%F)"

step 7 "RBAC: STUDENT JWT against /api/v1/settings should 403"
note "Set SAM_STUDENT_JWT to test. Skipping if unset."
if [[ -n "${SAM_STUDENT_JWT:-}" ]]; then
  status=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $SAM_STUDENT_JWT" "$API/api/v1/settings")
  echo "  /api/v1/settings as STUDENT → $status (expect 403)"
fi

step 8 "Manual: in Telegram DM as FACULTY, run:"
cat <<'EOF'
  show CS201 attendance for today
  list students in CSE-3A
  who hasn't submitted assignment 3
  generate mcq attendance for DSA       (after uploading material PDF)
  start mcq attendance CS201             (after approving bank)
  bring up the attendance sheet for CS201
EOF

step 9 "Frontend smoke (open in browser):"
cat <<'EOF'
  http://localhost:3000/app/faculty/attendance
  http://localhost:3000/app/faculty/assignments
  http://localhost:3000/app/super-admin/materials   (super-admin)
  http://localhost:3000/app/super-admin/settings    (super-admin)

  Sanity: log out, log in as STUDENT — /app/super-admin/* should redirect to /app.
EOF

echo ""
echo "✓ End-to-end checklist complete."
