"""
Idempotent migration v5: per-faculty weekly timetable.

  - timetable_entries
        One row per (user, day_of_week, time block). Multiple rows per day
        are allowed (different periods). Indexed by (user_id, day_of_week)
        for the student↔faculty status query path.

Run AFTER migrate_v4_foundations.py.

    python scripts/migrate_v5_timetable.py
"""

import sys
from pathlib import Path

import psycopg2
from psycopg2 import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config_loader import Config


MIGRATION_SQL = """
-- ----------------------------------------------------------------------
-- timetable_entries
--   day_of_week: 0=Monday … 6=Sunday (ISO).
--   source: 'manual' | 'photo_ocr' | 'voice' | 'csv' | 'pdf' — useful for
--           audit of OCR-derived rows that may want re-review.
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS timetable_entries (
    id           SERIAL PRIMARY KEY,
    org_id       INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day_of_week  SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    start_time   TIME NOT NULL,
    end_time     TIME NOT NULL,
    subject      VARCHAR(200),
    room         VARCHAR(100),
    batch        VARCHAR(100),
    source       VARCHAR(20) NOT NULL DEFAULT 'manual',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK (start_time < end_time)
);

CREATE INDEX IF NOT EXISTS idx_timetable_user_day
    ON timetable_entries(user_id, day_of_week);
CREATE INDEX IF NOT EXISTS idx_timetable_org
    ON timetable_entries(org_id);
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
        print("✅ v5 migration applied: timetable_entries")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
