import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from utils.config_loader import Config
import threading
from typing import Optional


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
# INTERNAL CONNECTION (NO RLS) – USE CAREFULLY
# Only for organizations table or bootstrap logic
# ======================================================

@contextmanager
def get_system_db():
    """
    Use ONLY for:
    - organizations lookup
    - bootstrap operations

    RLS is NOT applied here.
    """
    pool = get_pool()
    conn = pool.getconn()

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
        pool.putconn(conn)


# ======================================================
# TENANT-AWARE DB CONTEXT (RLS ENFORCED)
# ======================================================

@contextmanager
def get_db(org_id: int):
    """
    Secure DB session with tenant isolation.

    - Injects app.org_id into PostgreSQL session.
    - Enforces RLS automatically.
    - Commits on success.
    - Rolls back on failure.
    """

    if not isinstance(org_id, int):
        raise ValueError("org_id must be a valid integer")

    pool = get_pool()
    conn = pool.getconn()

    try:
        conn.autocommit = False
        cur = conn.cursor()

        # Inject tenant context for RLS
        cur.execute("SET LOCAL app.org_id = %s;", (str(org_id),))

        yield cur

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        pool.putconn(conn)


# ======================================================
# HELPER FUNCTIONS (DAL LAYER)
# ======================================================

def create_user(email: str, full_name: str, role: str, invite_code: str) -> int:
    """
    Transactional user creation.

    1. Validate invite code.
    2. Fetch org_id.
    3. Insert user under tenant context.
    """

    if role not in ("ADMIN", "FACULTY"):
        raise ValueError("Invalid role")

    # Step 1: Validate invite code (system-level access)
    with get_system_db() as cur:
        cur.execute(
            "SELECT id FROM organizations WHERE invite_code = %s;",
            (invite_code,)
        )
        org = cur.fetchone()

        if not org:
            raise ValueError("Invalid invite code")

        org_id = org["id"]

    # Step 2: Insert user under RLS context
    with get_db(org_id) as cur:
        cur.execute("""
            INSERT INTO users (org_id, email, full_name, role)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
        """, (org_id, email, full_name, role))

        return cur.fetchone()["id"]


def log_audit_action(org_id: int, user_id: Optional[int],
                     action: str, metadata: Optional[dict] = None):
    """
    Insert audit log entry.

    - RLS protected
    - JSONB metadata supported
    """

    if not action:
        raise ValueError("Action must be provided")

    with get_db(org_id) as cur:
        cur.execute("""
            INSERT INTO audit_logs (org_id, user_id, action, metadata)
            VALUES (%s, %s, %s, %s);
        """, (org_id, user_id, action, metadata))
