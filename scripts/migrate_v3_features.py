"""
Idempotent migration v3: saved groups + WhatsApp audit log.

Run after migrate_phone_and_student.py.

    python scripts/migrate_v3_features.py
"""

import sys
from pathlib import Path

import psycopg2
from psycopg2 import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config_loader import Config


MIGRATION_SQL = """
-- ----------------------------------------------------------------------
-- Saved groups (faculty-defined cohorts of users — e.g. "CSE-3A")
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_groups (
    id          SERIAL PRIMARY KEY,
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name        VARCHAR(100) NOT NULL,
    description TEXT,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS user_group_members (
    group_id  INTEGER NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    added_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (group_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_groups_org
    ON user_groups(org_id);
CREATE INDEX IF NOT EXISTS idx_user_group_members_user
    ON user_group_members(user_id);


-- ----------------------------------------------------------------------
-- WhatsApp audit trail (compliance + debugging)
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS whatsapp_audit (
    id          SERIAL PRIMARY KEY,
    org_id      INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    phone       VARCHAR(20),
    direction   VARCHAR(10) NOT NULL CHECK (direction IN ('inbound','outbound')),
    msg_type    VARCHAR(20),     -- text | document | interactive | template | reminder | broadcast
    body        TEXT,
    intent      VARCHAR(40),
    metadata    JSONB,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wa_audit_org   ON whatsapp_audit(org_id);
CREATE INDEX IF NOT EXISTS idx_wa_audit_phone ON whatsapp_audit(phone);
CREATE INDEX IF NOT EXISTS idx_wa_audit_time  ON whatsapp_audit(created_at);


-- ----------------------------------------------------------------------
-- Lightweight meetings — created from a faculty WhatsApp upload, do NOT
-- write to anyone's Google Calendar. We email an ICS attachment so
-- recipients can add it to their own calendar manually.
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lightweight_meetings (
    id            SERIAL PRIMARY KEY,
    org_id        INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    organizer_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title         TEXT NOT NULL,
    start_time    TIMESTAMP NOT NULL,
    end_time      TIMESTAMP NOT NULL,
    location      TEXT,
    agenda        TEXT,
    attendees     JSONB NOT NULL DEFAULT '[]'::jsonb,
    ics_path      TEXT,
    status        VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED'
                   CHECK (status IN ('SCHEDULED','CANCELLED','COMPLETED')),
    upload_id     INTEGER REFERENCES pending_uploads(id) ON DELETE SET NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK (start_time < end_time)
);

CREATE INDEX IF NOT EXISTS idx_lite_meetings_org   ON lightweight_meetings(org_id);
CREATE INDEX IF NOT EXISTS idx_lite_meetings_start ON lightweight_meetings(start_time);
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
        print("✅ v3 migration applied: user_groups, user_group_members, whatsapp_audit")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
