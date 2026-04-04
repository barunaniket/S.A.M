"""
lifecycle_store.py
------------------
DB-backed meeting lifecycle store (Feature 11).

Previously in-memory (dict), now persisted to a `meeting_lifecycle` table so
state survives server restarts. The table is created automatically on first use.
"""

from enum import Enum

from src.utils.db_handler import get_db_connection, release_db_connection


class MeetingStatus(str, Enum):
    PENDING     = "PENDING"
    SCHEDULED   = "SCHEDULED"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED   = "CANCELLED"


_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS meeting_lifecycle (
    meeting_id  VARCHAR PRIMARY KEY,
    status      VARCHAR NOT NULL DEFAULT 'PENDING',
    updated_at  TIMESTAMP DEFAULT NOW()
);
"""


class LifecycleStore:

    def _ensure_table(self):
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(_TABLE_DDL)
            conn.commit()
            cur.close()
        except Exception as e:
            print(f"[lifecycle_store] Table init failed: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                release_db_connection(conn)

    def create_meeting(self, meeting_id: str):
        self._ensure_table()
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO meeting_lifecycle (meeting_id, status)
                VALUES (%s, 'PENDING')
                ON CONFLICT (meeting_id) DO NOTHING;
                """,
                (meeting_id,),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            print(f"[lifecycle_store] create_meeting failed: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                release_db_connection(conn)

    def get_status(self, meeting_id: str):
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT status FROM meeting_lifecycle WHERE meeting_id = %s;",
                (meeting_id,),
            )
            row = cur.fetchone()
            cur.close()
            if row:
                return MeetingStatus(row["status"])
            return None
        except Exception:
            return None
        finally:
            if conn:
                release_db_connection(conn)

    def update_status(self, meeting_id: str, new_status):
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE meeting_lifecycle
                SET status = %s, updated_at = NOW()
                WHERE meeting_id = %s
                RETURNING meeting_id;
                """,
                (str(new_status), meeting_id),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            return bool(row)
        except Exception as e:
            print(f"[lifecycle_store] update_status failed: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                release_db_connection(conn)


lifecycle_store = LifecycleStore()
