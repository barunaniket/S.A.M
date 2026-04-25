"""
Idempotent migration:
  - add users.phone_number (unique when present)
  - add users.department
  - extend role check to include STUDENT
  - create pending_uploads table

Safe to run on a database that already has the v1 schema.
"""

import sys
from pathlib import Path

import psycopg2
from psycopg2 import OperationalError

# Allow running as `python scripts/migrate_phone_and_student.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config_loader import Config


MIGRATION_SQL = """
-- USERS: add phone_number, department, expand role check
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS department  VARCHAR(100);

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role IN ('ADMIN', 'FACULTY', 'STUDENT'));

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone
    ON users(phone_number) WHERE phone_number IS NOT NULL;

-- PENDING UPLOADS
CREATE TABLE IF NOT EXISTS pending_uploads (
    id          SERIAL PRIMARY KEY,
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    uploaded_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_path   TEXT NOT NULL,
    parse_kind  VARCHAR(20) NOT NULL,
    parsed      JSONB NOT NULL,
    status      VARCHAR(20) NOT NULL DEFAULT 'PARSED'
                CHECK (status IN ('PARSED','EXECUTED','DISCARDED')),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at  TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '24 hours')
);

CREATE INDEX IF NOT EXISTS idx_pending_uploads_org
    ON pending_uploads(org_id);
CREATE INDEX IF NOT EXISTS idx_pending_uploads_user
    ON pending_uploads(uploaded_by);
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
        print("✅ Migration applied: phone_number, department, STUDENT role, pending_uploads")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
