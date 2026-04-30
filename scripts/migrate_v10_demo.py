"""
Idempotent migration v10: chat-first onboarding + period-aware lookup demo.

  - onboarding_tokens — short-lived OAuth-state tokens for chat-first sign-up
    (parallel to telegram_pairing_codes which serves the web-first flow)
  - users.office_location — "she should be in her cabin, Room 312" fallback
  - users.batch — student batch e.g. CSE-3A; used during student onboarding

Run AFTER migrate_v9_telegram.py.

    python scripts/migrate_v10_demo.py
"""

import sys
from pathlib import Path

import psycopg2
from psycopg2 import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config_loader import Config


MIGRATION_SQL = """
-- ----------------------------------------------------------------------
-- USERS: office_location + batch (used by chat-first onboarding +
-- period-aware "where will Prof X be?" lookup)
-- ----------------------------------------------------------------------
ALTER TABLE users ADD COLUMN IF NOT EXISTS office_location VARCHAR(120);
ALTER TABLE users ADD COLUMN IF NOT EXISTS batch           VARCHAR(32);

CREATE INDEX IF NOT EXISTS idx_users_batch
    ON users(batch) WHERE batch IS NOT NULL;


-- ----------------------------------------------------------------------
-- onboarding_tokens
--   Generated when an unknown chat user DMs the bot for the first time.
--   The token is embedded in the Google OAuth `state` param; on callback
--   we look up the row, bind the channel identifier (chat_id / phone)
--   to the user being created, and notify them on the same channel.
--
--   Shape mirrors telegram_pairing_codes but is channel-aware so the same
--   table works for WhatsApp later. `identifier` is chat_id (digits) for
--   Telegram or phone digits for WhatsApp.
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS onboarding_tokens (
    token            VARCHAR(64) PRIMARY KEY,
    channel          VARCHAR(16) NOT NULL CHECK (channel IN ('telegram','whatsapp')),
    identifier       VARCHAR(64) NOT NULL,
    telegram_username VARCHAR(64),
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at       TIMESTAMP NOT NULL,
    consumed         BOOLEAN DEFAULT FALSE,
    consumed_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_onboarding_open
    ON onboarding_tokens(channel, identifier)
    WHERE consumed = FALSE;
CREATE INDEX IF NOT EXISTS idx_onboarding_expiry
    ON onboarding_tokens(expires_at)
    WHERE consumed = FALSE;
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
        print("✅ v10 migration applied: users.office_location + batch, "
              "onboarding_tokens table")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
