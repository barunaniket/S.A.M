"""
Idempotent migration v6: org-wide academic calendar.

  - academic_events
        Holidays, exam windows, breaks, generic events. Date range so a row
        can model "Mid-sem exams: Apr 15 – Apr 22". The scheduling guard
        in meeting_creator queries this table before allowing a slot.

Run AFTER migrate_v5_timetable.py.

    python scripts/migrate_v6_academic_calendar.py
"""

import sys
from pathlib import Path

import psycopg2
from psycopg2 import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config_loader import Config


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS academic_events (
    id                SERIAL PRIMARY KEY,
    org_id            INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    kind              VARCHAR(20) NOT NULL CHECK (kind IN ('HOLIDAY','EXAM','BREAK','EVENT')),
    title             VARCHAR(200) NOT NULL,
    start_date        DATE NOT NULL,
    end_date          DATE NOT NULL,
    source_upload_id  INTEGER REFERENCES pending_uploads(id) ON DELETE SET NULL,
    created_by        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK (start_date <= end_date)
);

CREATE INDEX IF NOT EXISTS idx_academic_events_org_dates
    ON academic_events(org_id, start_date, end_date);
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
        print("✅ v6 migration applied: academic_events")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
