"""
Idempotent migration v13: spec-completion features.

  - course_materials       PDF/slide library used for MCQ generation +
                           material lookup (faculty/super-admin uploads)
  - mcq_question_bank      Replaces the hardcoded QUESTION_BANK dict in
                           src/services/attendance_mcq.py — generated from
                           PDFs (or manually authored), faculty-approved
  - org_settings           Per-org feature toggles (super-admin controlled).
                           Initial keys: mcq_attendance_enabled (bool),
                           mcq_threshold (int), mcq_window_seconds (int),
                           assignment_nudge_hours (list[float]),
                           poll_window_seconds (int).
  - assignment_reminders   Mirrors task_reminders for the deadline-nudge
                           Celery job. One row per scheduled fire.

Run AFTER migrate_v12_mvp.py.

    python scripts/migrate_v13_spec.py
"""

import sys
from pathlib import Path

import psycopg2
from psycopg2 import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config_loader import Config


MIGRATION_SQL = """
-- ----------------------------------------------------------------------
-- course_materials
--   PDF/slide library. file_path is a filesystem path (matches the
--   convention used by assignments.body_file_path). extracted_text is
--   populated by file_ingestor.parse_file() at upload time so the MCQ
--   generator doesn't need to re-OCR.
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS course_materials (
    id              SERIAL PRIMARY KEY,
    org_id          INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    subject         VARCHAR(120) NOT NULL,
    batch           VARCHAR(32),
    title           VARCHAR(200) NOT NULL,
    file_path       TEXT,
    mime_type       VARCHAR(64),
    extracted_text  TEXT,
    uploaded_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_course_materials_org_subject
    ON course_materials(org_id, subject, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_course_materials_uploaded_by
    ON course_materials(uploaded_by, created_at DESC);


-- ----------------------------------------------------------------------
-- mcq_question_bank
--   One row per question. choices is a JSONB list of 4 strings.
--   correct_index is 0-3. approved_at NULL = generated but not yet
--   approved by faculty (cannot be used in a session).
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mcq_question_bank (
    id                  SERIAL PRIMARY KEY,
    org_id              INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    subject             VARCHAR(120) NOT NULL,
    source_material_id  INTEGER REFERENCES course_materials(id) ON DELETE SET NULL,
    question            TEXT NOT NULL,
    choices             JSONB NOT NULL,
    correct_index       SMALLINT NOT NULL CHECK (correct_index BETWEEN 0 AND 3),
    generated_by        VARCHAR(16) NOT NULL DEFAULT 'llm'
                          CHECK (generated_by IN ('llm','manual')),
    approved_by         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approved_at         TIMESTAMP,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mcq_bank_org_subject_approved
    ON mcq_question_bank(org_id, subject, approved_at);
CREATE INDEX IF NOT EXISTS idx_mcq_bank_source
    ON mcq_question_bank(source_material_id);


-- ----------------------------------------------------------------------
-- org_settings
--   Per-org feature toggles. value is JSONB so we can store bools,
--   ints, lists. Super-admin reads/writes via /api/v1/settings.
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS org_settings (
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    key         VARCHAR(64) NOT NULL,
    value       JSONB NOT NULL,
    updated_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (org_id, key)
);


-- ----------------------------------------------------------------------
-- assignment_reminders
--   Mirrors task_reminders (migrate_v7_tasks.py). One row per scheduled
--   Celery fire — used to deduplicate when assignments get rescheduled
--   and to surface "next reminder at" in the faculty UI.
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS assignment_reminders (
    id              SERIAL PRIMARY KEY,
    assignment_id   INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    fires_at        TIMESTAMP NOT NULL,
    kind            VARCHAR(16) NOT NULL
                      CHECK (kind IN ('24h','1h','overdue','custom')),
    celery_task_id  VARCHAR(128),
    fired           BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_assignment_reminders_due
    ON assignment_reminders(fires_at, fired);
CREATE INDEX IF NOT EXISTS idx_assignment_reminders_assignment
    ON assignment_reminders(assignment_id);
"""


# Default settings rows seeded for every existing organization. Idempotent
# via ON CONFLICT DO NOTHING.
DEFAULT_SETTINGS = [
    ("mcq_attendance_enabled", "true"),
    ("mcq_threshold", "4"),
    ("mcq_window_seconds", "15"),
    ("assignment_nudge_hours", "[24, 1]"),
    ("poll_window_seconds", "60"),
]


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

                cur.execute("SELECT id FROM organizations;")
                orgs = [r[0] for r in cur.fetchall()]
                for org_id in orgs:
                    for key, value in DEFAULT_SETTINGS:
                        cur.execute(
                            """
                            INSERT INTO org_settings (org_id, key, value)
                            VALUES (%s, %s, %s::jsonb)
                            ON CONFLICT (org_id, key) DO NOTHING;
                            """,
                            (org_id, key, value),
                        )
        print("✅ v13 migration applied: course_materials, mcq_question_bank, "
              "org_settings, assignment_reminders. Default settings seeded "
              f"for {len(orgs)} org(s).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
