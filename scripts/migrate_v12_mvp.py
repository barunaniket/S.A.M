"""
Idempotent migration v12: MVP demo features.

  - poll_sessions          one row per faculty-triggered Quick Poll attendance
                           (single 'I'm here' button fanned out to a batch)
  - assignments            faculty-authored assignments (subject + title +
                           question body either as text or an uploaded photo)
  - assignment_submissions one row per (assignment, student) — student photo
                           submissions, with PENDING → CONFIRMED state

Also drops the FK from attendance_records.session_id to mcq_sessions so
poll_sessions ids can land in the same column.

Run AFTER migrate_v11_mcq.py.

    python scripts/migrate_v12_mvp.py
"""

import sys
from pathlib import Path

import psycopg2
from psycopg2 import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config_loader import Config


MIGRATION_SQL = """
-- ----------------------------------------------------------------------
-- poll_sessions
--   Mirror of mcq_sessions, but for the start-of-class Quick Poll
--   (single button, no questions, no per-q timing).
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS poll_sessions (
    id          SERIAL PRIMARY KEY,
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    faculty_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    batch       VARCHAR(32)  NOT NULL,
    subject     VARCHAR(120) NOT NULL,
    status      VARCHAR(16)  NOT NULL DEFAULT 'IN_PROGRESS'
                  CHECK (status IN ('IN_PROGRESS','CLOSED','CANCELLED')),
    started_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at   TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_poll_sessions_faculty
    ON poll_sessions(faculty_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_poll_sessions_status
    ON poll_sessions(status, started_at DESC);


-- ----------------------------------------------------------------------
-- attendance_records — drop the MCQ-only FK so poll session ids can use
-- the same session_id column. (source + session_id together identify the
-- session kind; the FK was unnecessarily restrictive.)
-- ----------------------------------------------------------------------
ALTER TABLE attendance_records
    DROP CONSTRAINT IF EXISTS attendance_records_session_id_fkey;


-- ----------------------------------------------------------------------
-- assignments
--   Faculty-authored. body_text OR body_file_path (one of, not both,
--   though the schema doesn't enforce that — UI does).
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS assignments (
    id              SERIAL PRIMARY KEY,
    org_id          INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    faculty_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    batch           VARCHAR(32)  NOT NULL,
    subject         VARCHAR(120) NOT NULL,
    title           VARCHAR(200) NOT NULL,
    body_text       TEXT,
    body_file_path  TEXT,
    due_at          TIMESTAMP,
    status          VARCHAR(16)  NOT NULL DEFAULT 'OPEN'
                      CHECK (status IN ('OPEN','CLOSED','ARCHIVED')),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_assignments_batch_status
    ON assignments(batch, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assignments_faculty
    ON assignments(faculty_id, status, created_at DESC);


-- ----------------------------------------------------------------------
-- assignment_submissions
--   UNIQUE(assignment_id, student_id) means a re-submission overwrites
--   (UPSERT in service code).
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS assignment_submissions (
    id             SERIAL PRIMARY KEY,
    org_id         INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    assignment_id  INTEGER NOT NULL REFERENCES assignments(id)   ON DELETE CASCADE,
    student_id     INTEGER NOT NULL REFERENCES users(id)         ON DELETE CASCADE,
    file_path      TEXT NOT NULL,
    caption        TEXT,
    status         VARCHAR(16) NOT NULL DEFAULT 'PENDING'
                     CHECK (status IN ('PENDING','CONFIRMED','DISCARDED','REVIEWED')),
    submitted_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    confirmed_at   TIMESTAMP,
    UNIQUE (assignment_id, student_id)
);

CREATE INDEX IF NOT EXISTS idx_subm_student
    ON assignment_submissions(student_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_subm_assignment
    ON assignment_submissions(assignment_id, status);
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
        print("✅ v12 migration applied: poll_sessions, assignments, "
              "assignment_submissions (and dropped attendance_records "
              "session_id FK).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
