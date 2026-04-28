"""
Idempotent migration v4: foundation tables for the v1 vision.

  - extend users.role CHECK to add SUPER_ADMIN and BOOKING_AUTHORITY
  - add users.briefing_time / users.timezone / users.briefing_enabled?
    (we keep these on a separate user_preferences table — easier to extend)
  - create conversation_log (full per-user message history, beyond the 30-min Redis cache)
  - create user_context (per-user JSONB profile + learned facts)
  - create user_preferences (briefing time/tz/toggle)

Run AFTER migrate_v3_features.py.

    python scripts/migrate_v4_foundations.py
"""

import sys
from pathlib import Path

import psycopg2
from psycopg2 import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config_loader import Config


MIGRATION_SQL = """
-- ----------------------------------------------------------------------
-- USERS: extend role CHECK to include SUPER_ADMIN and BOOKING_AUTHORITY
-- (mirrors the pattern in migrate_phone_and_student.py)
-- ----------------------------------------------------------------------
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role IN ('ADMIN', 'FACULTY', 'STUDENT',
                    'SUPER_ADMIN', 'BOOKING_AUTHORITY'));


-- ----------------------------------------------------------------------
-- conversation_log
--   Persistent record of every inbound/outbound turn across all channels.
--   Redis (conversation_store) keeps the last 12 turns hot; this is the
--   permanent ledger the agent and humans can audit later.
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversation_log (
    id          BIGSERIAL PRIMARY KEY,
    org_id      INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    phone       VARCHAR(20),
    channel     VARCHAR(20) NOT NULL DEFAULT 'whatsapp',
    role        VARCHAR(16) NOT NULL CHECK (role IN ('user','assistant','system','tool')),
    content     TEXT NOT NULL,
    intent      VARCHAR(40),
    metadata    JSONB,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conversation_log_user_time
    ON conversation_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_log_org_time
    ON conversation_log(org_id, created_at DESC);


-- ----------------------------------------------------------------------
-- user_context
--   Per-user JSONB profile + learned facts. Shape is intentionally loose
--   so the agent can write whatever it picks up over time without a
--   migration. Examples:
--     profile        = {"preferred_meeting_length": 30, "no_meeting_days": ["FRI"]}
--     learned_facts  = {"frequent_collaborators": ["Prof Mehta"]}
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_context (
    user_id        INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    profile        JSONB NOT NULL DEFAULT '{}'::jsonb,
    learned_facts  JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- ----------------------------------------------------------------------
-- user_preferences
--   Daily briefing window + timezone + on/off toggle. The Celery beat
--   tick_user_briefings task polls this every 5 minutes.
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id           INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    briefing_time     TIME NOT NULL DEFAULT '07:00',
    timezone          VARCHAR(64) NOT NULL DEFAULT 'Asia/Kolkata',
    briefing_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_preferences_briefing
    ON user_preferences(briefing_enabled, briefing_time)
    WHERE briefing_enabled = TRUE;
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
        print("✅ v4 migration applied: roles extended, conversation_log, "
              "user_context, user_preferences")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
