"""
Idempotent migration v8: booking authority flow + briefing prefs hooks.

  - room_bookings
        Tracks room/lab/hall booking requests. SAM never auto-books — when a
        meeting needs a venue, request_booking() inserts here PENDING and
        notifies users with role=BOOKING_AUTHORITY. They tap approve/deny
        on WhatsApp (or via the /app/booking/queue page); on approve the
        meeting flips from BOOKING_PENDING → CONFIRMED.

  - meetings.requires_booking BOOL DEFAULT FALSE
        Set true when a meeting was created with a room request.

  - meetings.status: extended to include BOOKING_PENDING.

Class-enrolment data model decision: we reuse `user_groups` with a naming
convention (group name == batch label, e.g. "CSE-3A"). The cancellation
service looks up the group whose name matches the timetable entry's `batch`
field and broadcasts to its members. No new table needed.

Run AFTER migrate_v7_tasks.py.

    python scripts/migrate_v8_booking_briefing.py
"""

import sys
from pathlib import Path

import psycopg2
from psycopg2 import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config_loader import Config


MIGRATION_SQL = """
-- ----------------------------------------------------------------------
-- meetings: extend status CHECK + add requires_booking flag.
-- The original CHECK was ('PENDING','CONFIRMED','CANCELLED').
-- ----------------------------------------------------------------------
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS requires_booking BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE meetings DROP CONSTRAINT IF EXISTS meetings_status_check;
ALTER TABLE meetings ADD CONSTRAINT meetings_status_check
    CHECK (status IN ('PENDING','CONFIRMED','CANCELLED','BOOKING_PENDING'));


-- ----------------------------------------------------------------------
-- room_bookings
--   meeting_id may be NULL because a booking request can also be made
--   ad-hoc (just "I need Lab 4 Friday afternoon") without a Calendar
--   meeting yet. The state machine is PENDING → APPROVED|DENIED.
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS room_bookings (
    id                    SERIAL PRIMARY KEY,
    org_id                INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    meeting_id            VARCHAR(200),     -- google calendar event id (string, like meetings.id)
    requested_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    booking_authority_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    room_label            VARCHAR(200),
    starts_at             TIMESTAMP,
    ends_at               TIMESTAMP,
    purpose               TEXT,
    status                VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                          CHECK (status IN ('PENDING','APPROVED','DENIED','CANCELLED')),
    decided_at            TIMESTAMP,
    notes                 TEXT,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_room_bookings_org_status
    ON room_bookings(org_id, status);
CREATE INDEX IF NOT EXISTS idx_room_bookings_requester
    ON room_bookings(requested_by);
"""


def main() -> None:
    try:
        conn = psycopg2.connect(Config.DATABASE_URL)
    except OperationalError as err:
        print(f"❌ Could not connect to DB: {err}")
        sys.exit(1)

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(MIGRATION_SQL)
        print("✅ v8 migration applied: room_bookings, BOOKING_PENDING status")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
