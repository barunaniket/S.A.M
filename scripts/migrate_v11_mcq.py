"""
Idempotent migration v11: MCQ-based attendance.

  - mcq_sessions      one row per faculty-triggered MCQ quiz
                      (5 questions × 15s default)
  - mcq_responses     each student's answer to each question
  - attendance_records ground-truth attendance after scoring,
                      with optional teacher override

Run AFTER migrate_v10_demo.py.

    python scripts/migrate_v11_mcq.py
"""

import sys
from pathlib import Path

import psycopg2
from psycopg2 import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config_loader import Config


MIGRATION_SQL = """
-- ----------------------------------------------------------------------
-- mcq_sessions
--   The whole quiz lives here as JSONB so we don't need a per-question
--   row. `questions` is a list of {text, choices: [a,b,c,d], correct: int}.
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcq_sessions (
    id              SERIAL PRIMARY KEY,
    org_id          INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    faculty_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    batch           VARCHAR(32)  NOT NULL,
    subject         VARCHAR(120) NOT NULL,
    questions       JSONB        NOT NULL,
    threshold       SMALLINT     NOT NULL DEFAULT 4,    -- ≥ N correct → present
    seconds_per_q   SMALLINT     NOT NULL DEFAULT 15,
    status          VARCHAR(16)  NOT NULL DEFAULT 'IN_PROGRESS'
                      CHECK (status IN ('IN_PROGRESS','CLOSED','CANCELLED')),
    started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at       TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mcq_sessions_org    ON mcq_sessions(org_id);
CREATE INDEX IF NOT EXISTS idx_mcq_sessions_status ON mcq_sessions(status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_mcq_sessions_faculty ON mcq_sessions(faculty_id, started_at DESC);


-- ----------------------------------------------------------------------
-- mcq_responses
--   One row per (student × question). UNIQUE constraint stops a student
--   from answering the same question twice.
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcq_responses (
    id           SERIAL PRIMARY KEY,
    session_id   INTEGER NOT NULL REFERENCES mcq_sessions(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES users(id)        ON DELETE CASCADE,
    q_index      SMALLINT NOT NULL,
    choice       SMALLINT NOT NULL CHECK (choice BETWEEN 0 AND 3),
    answered_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (session_id, user_id, q_index)
);

CREATE INDEX IF NOT EXISTS idx_mcq_responses_session ON mcq_responses(session_id);
CREATE INDEX IF NOT EXISTS idx_mcq_responses_user    ON mcq_responses(user_id);


-- ----------------------------------------------------------------------
-- attendance_records
--   The ground truth. UNIQUE (user_id, subject, class_date) makes
--   re-running an MCQ session for the same class idempotent (later
--   sessions update earlier ones via ON CONFLICT).
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attendance_records (
    id           SERIAL PRIMARY KEY,
    org_id       INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject      VARCHAR(120) NOT NULL,
    class_date   DATE         NOT NULL DEFAULT CURRENT_DATE,
    status       VARCHAR(16)  NOT NULL CHECK (status IN ('PRESENT','ABSENT')),
    source       VARCHAR(32)  NOT NULL DEFAULT 'mcq',
    score        SMALLINT,
    session_id   INTEGER REFERENCES mcq_sessions(id) ON DELETE SET NULL,
    marked_by    INTEGER REFERENCES users(id)        ON DELETE SET NULL,
    marked_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    overridden   BOOLEAN DEFAULT FALSE,
    UNIQUE (user_id, subject, class_date)
);

CREATE INDEX IF NOT EXISTS idx_attendance_user_date
    ON attendance_records(user_id, class_date DESC);
CREATE INDEX IF NOT EXISTS idx_attendance_org_subject_date
    ON attendance_records(org_id, subject, class_date DESC);
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
        print("✅ v11 migration applied: mcq_sessions, mcq_responses, "
              "attendance_records")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
