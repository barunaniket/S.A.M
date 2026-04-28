"""
Idempotent migration v7: bulk task assignment + smart reminders.

  - tasks
        One row per assignee per task. An admin uploads a sheet/PDF/voice
        memo with N tuples (Prof X: Y by Friday) and one row per tuple is
        created. Reminders are scheduled via Celery 24h/4h/1h before
        the deadline.

  - task_reminders
        Bookkeeping for the scheduled Celery reminders (so the admin UI can
        show "next reminder fires at …" and tests can fire them on demand).

Run AFTER migrate_v6_academic_calendar.py.

    python scripts/migrate_v7_tasks.py
"""

import sys
from pathlib import Path

import psycopg2
from psycopg2 import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config_loader import Config


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id              SERIAL PRIMARY KEY,
    org_id          INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    assigned_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    assignee_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    -- Free-form fallback when the assignee is not a registered user.
    assignee_name   VARCHAR(200),
    assignee_email  VARCHAR(200),
    assignee_phone  VARCHAR(40),
    title           VARCHAR(300) NOT NULL,
    description     TEXT,
    deadline        TIMESTAMP,
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING','DONE','OVERDUE','CANCELLED')),
    source_upload_id INTEGER REFERENCES pending_uploads(id) ON DELETE SET NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tasks_org           ON tasks(org_id);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee      ON tasks(assignee_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned_by   ON tasks(assigned_by, status);
CREATE INDEX IF NOT EXISTS idx_tasks_deadline      ON tasks(deadline) WHERE status = 'PENDING';


CREATE TABLE IF NOT EXISTS task_reminders (
    id              SERIAL PRIMARY KEY,
    task_id         INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    fires_at        TIMESTAMP NOT NULL,
    kind            VARCHAR(8) NOT NULL CHECK (kind IN ('24h','4h','1h','overdue')),
    celery_task_id  VARCHAR(80),
    fired           BOOLEAN NOT NULL DEFAULT FALSE,
    fired_at        TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_reminders_task ON task_reminders(task_id);
CREATE INDEX IF NOT EXISTS idx_task_reminders_fires ON task_reminders(fires_at)
    WHERE fired = FALSE;
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
        print("✅ v7 migration applied: tasks, task_reminders")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
