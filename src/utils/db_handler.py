import json
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from src.utils.config_loader import Config
import threading
from typing import Optional, List, Dict, Any


# ======================================================
# CONNECTION POOL (Thread Safe – FastAPI Compatible)
# ======================================================

_connection_pool: Optional[pool.SimpleConnectionPool] = None
_pool_lock = threading.Lock()


def init_connection_pool():
    global _connection_pool
    with _pool_lock:
        if _connection_pool is None:
            _connection_pool = pool.SimpleConnectionPool(
                minconn=2,
                maxconn=20,
                dsn=Config.DATABASE_URL,
                cursor_factory=RealDictCursor
            )


def get_pool():
    if _connection_pool is None:
        init_connection_pool()
    return _connection_pool


# ======================================================
# RAW CONNECTION — for modules that manage their own cursors
# ======================================================

def get_db_connection():
    """
    Returns a raw psycopg2 connection from the pool.

    The CALLER is responsible for commit/rollback/close.
    Use this only in modules that manage their own cursor lifecycle
    (e.g. self_healing_calendar, notification, meeting_fetcher).
    """
    conn_pool = get_pool()
    conn = conn_pool.getconn()
    conn.autocommit = False
    return conn


def release_db_connection(conn):
    """Return a connection obtained via get_db_connection() back to the pool."""
    conn_pool = get_pool()
    conn_pool.putconn(conn)


# ======================================================
# SYSTEM DB CONTEXT (NO RLS) — organisations / bootstrap
# ======================================================

@contextmanager
def get_system_db():
    """
    Use ONLY for:
    - organizations lookup
    - bootstrap operations

    RLS is NOT applied here.
    """
    conn_pool = get_pool()
    conn = conn_pool.getconn()

    try:
        conn.autocommit = False
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn_pool.putconn(conn)


# ======================================================
# TENANT-AWARE DB CONTEXT (RLS ENFORCED)
# ======================================================

@contextmanager
def get_db(org_id: int):
    """
    Secure DB session with tenant isolation.

    - Injects app.org_id into PostgreSQL session.
    - Enforces RLS automatically.
    - Commits on success, rolls back on failure.
    """

    if not isinstance(org_id, int):
        raise ValueError("org_id must be a valid integer")

    conn_pool = get_pool()
    conn = conn_pool.getconn()

    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute("SET LOCAL app.org_id = %s;", (str(org_id),))
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn_pool.putconn(conn)


# ======================================================
# HELPER FUNCTIONS (DAL LAYER)
# ======================================================

def create_user(email: str, full_name: str, role: str, invite_code: str) -> int:
    """
    Transactional user creation via invite code.

    1. Validate invite code → fetch org_id.
    2. Insert user under RLS tenant context.
    """

    if role not in ("ADMIN", "FACULTY"):
        raise ValueError("Invalid role")

    with get_system_db() as cur:
        cur.execute(
            "SELECT id FROM organizations WHERE invite_code = %s;",
            (invite_code,)
        )
        org = cur.fetchone()

        if not org:
            raise ValueError("Invalid invite code")

        org_id = org["id"]

    with get_db(org_id) as cur:
        cur.execute("""
            INSERT INTO users (org_id, email, full_name, role)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
        """, (org_id, email, full_name, role))

        return cur.fetchone()["id"]


def upsert_google_user(
    email: str,
    full_name: str,
    picture: str,
    access_token: str,
    encrypted_refresh_token: Optional[str],
    org_id: int = 1,
) -> Dict[str, Any]:
    """
    Insert or update a Google OAuth user.

    On first login the user is created; on subsequent logins the tokens
    and profile info are refreshed.

    Returns the full user row dict.
    """
    with get_system_db() as cur:
        cur.execute("""
            INSERT INTO users (org_id, email, full_name, picture_url, role,
                               access_token, encrypted_refresh_token)
            VALUES (%s, %s, %s, %s, 'FACULTY', %s, %s)
            ON CONFLICT (email) DO UPDATE
                SET full_name               = EXCLUDED.full_name,
                    picture_url             = EXCLUDED.picture_url,
                    access_token            = EXCLUDED.access_token,
                    encrypted_refresh_token = COALESCE(EXCLUDED.encrypted_refresh_token,
                                                       users.encrypted_refresh_token),
                    updated_at              = NOW()
            RETURNING id, org_id, email, full_name, picture_url, role,
                      access_token, encrypted_refresh_token;
        """, (org_id, email, full_name, picture, access_token, encrypted_refresh_token))

        return dict(cur.fetchone())


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """
    Look up a user by email address (system-level, no RLS).
    Returns None if the user does not exist.
    """
    with get_system_db() as cur:
        cur.execute(
            """SELECT id, org_id, email, full_name, picture_url, role,
                      phone_number, department,
                      access_token, encrypted_refresh_token
               FROM users WHERE email = %s;""",
            (email,)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_user_by_phone(phone_digits: str) -> Optional[Dict[str, Any]]:
    """
    Look up a user by phone number digits (system-level, no RLS).
    Matches both exact and 10-digit suffix.
    Returns None if not found.
    """
    if not phone_digits:
        return None
    with get_system_db() as cur:
        cur.execute(
            """SELECT id, org_id, email, full_name, role,
                      phone_number, department
               FROM users
               WHERE regexp_replace(phone_number, '[^0-9]', '', 'g') = %s
                  OR regexp_replace(phone_number, '[^0-9]', '', 'g') LIKE %s
               LIMIT 1;""",
            (phone_digits, f"%{phone_digits[-10:]}"),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_all_faculty() -> List[Dict[str, Any]]:
    """
    Return all faculty members from the faculty table.
    Used by user_resolver for fuzzy name matching.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, email, department, office_hours, tone, signature
            FROM faculty
            ORDER BY name ASC;
        """)
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    except Exception:
        conn.rollback()
        raise
    finally:
        release_db_connection(conn)


def get_faculty_by_id(faculty_id: int) -> Optional[Dict[str, Any]]:
    """
    Return a single faculty member by primary key.
    Used by LLMHandler to build context-aware email replies.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, email, department, office_hours, tone, signature
            FROM faculty
            WHERE id = %s;
        """, (faculty_id,))
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        release_db_connection(conn)


def log_audit_action(org_id: int, user_id: Optional[int],
                     action: str, metadata: Optional[dict] = None):
    """
    Insert an audit log entry (RLS protected).
    metadata is stored as JSONB.
    """

    if not action:
        raise ValueError("Action must be provided")

    with get_db(org_id) as cur:
        cur.execute("""
            INSERT INTO audit_logs (org_id, user_id, action, metadata)
            VALUES (%s, %s, %s, %s);
        """, (org_id, user_id, action, json.dumps(metadata) if metadata else None))
