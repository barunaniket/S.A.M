"""
group_service.py
----------------
CRUD for faculty-defined user groups (e.g. "CSE-3A") plus a helper that
expands a group into a list of attendee dicts the broadcast service can
consume directly.

All writes go through the RLS-enforced get_db() context.
"""

import logging
from typing import Any, Dict, List, Optional

from src.utils.db_handler import (
    get_db,
    get_db_connection,
    release_db_connection,
    set_org_rls,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Group CRUD
# ---------------------------------------------------------------------------

def create_group(org_id: int, name: str, description: Optional[str] = None,
                 created_by: Optional[int] = None) -> Dict[str, Any]:
    if not name or not name.strip():
        return {"success": False, "error": "Group name is required."}
    try:
        with get_db(org_id) as cur:
            cur.execute(
                """
                INSERT INTO user_groups (org_id, name, description, created_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (org_id, name) DO NOTHING
                RETURNING id, name, description, created_at;
                """,
                (org_id, name.strip(), description, created_by),
            )
            row = cur.fetchone()
        if not row:
            existing = get_group_by_name(org_id, name.strip())
            if existing:
                return {"success": True, "data": existing, "already_exists": True}
            return {"success": False, "error": "Could not create group."}
        return {"success": True, "data": dict(row)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_group_by_name(org_id: int, name: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        set_org_rls(cur, org_id)
        cur.execute(
            "SELECT id, name, description, created_at FROM user_groups "
            "WHERE org_id = %s AND LOWER(name) = LOWER(%s) LIMIT 1;",
            (org_id, name),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        release_db_connection(conn)


def list_groups(org_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        set_org_rls(cur, org_id)
        cur.execute(
            """
            SELECT g.id, g.name, g.description, g.created_at,
                   COUNT(m.user_id)::int AS member_count
              FROM user_groups g
              LEFT JOIN user_group_members m ON m.group_id = g.id
             WHERE g.org_id = %s
             GROUP BY g.id
             ORDER BY g.name ASC;
            """,
            (org_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)


def delete_group(org_id: int, group_id: int) -> Dict[str, Any]:
    try:
        with get_db(org_id) as cur:
            cur.execute(
                "DELETE FROM user_groups WHERE id = %s AND org_id = %s;",
                (group_id, org_id),
            )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------

def add_member(org_id: int, group_id: int, user_id: int) -> Dict[str, Any]:
    try:
        with get_db(org_id) as cur:
            cur.execute(
                """
                INSERT INTO user_group_members (group_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING;
                """,
                (group_id, user_id),
            )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def add_members_by_email(org_id: int, group_id: int,
                         emails: List[str]) -> Dict[str, Any]:
    """
    Bulk-add. Looks up each email in users (within org), inserts membership.
    Returns counts: matched, missing.
    """
    matched = 0
    missing: List[str] = []
    try:
        with get_db(org_id) as cur:
            for email in emails:
                if not email:
                    continue
                cur.execute(
                    "SELECT id FROM users WHERE org_id = %s AND email = %s LIMIT 1;",
                    (org_id, email),
                )
                row = cur.fetchone()
                if not row:
                    missing.append(email)
                    continue
                cur.execute(
                    """
                    INSERT INTO user_group_members (group_id, user_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING;
                    """,
                    (group_id, row["id"]),
                )
                matched += 1
        return {"success": True, "matched": matched, "missing": missing}
    except Exception as e:
        return {"success": False, "error": str(e)}


def remove_member(org_id: int, group_id: int, user_id: int) -> Dict[str, Any]:
    try:
        with get_db(org_id) as cur:
            cur.execute(
                "DELETE FROM user_group_members WHERE group_id = %s AND user_id = %s;",
                (group_id, user_id),
            )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_members(org_id: int, group_id: int) -> List[Dict[str, Any]]:
    """Return the user rows that belong to a group (id, email, name, phone, role)."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        set_org_rls(cur, org_id)
        cur.execute(
            """
            SELECT u.id, u.email, u.full_name AS name, u.phone_number AS phone,
                   u.telegram_chat_id, u.role, u.department
              FROM users u
              JOIN user_group_members m ON m.user_id = u.id
             WHERE m.group_id = %s AND u.org_id = %s
             ORDER BY u.full_name ASC;
            """,
            (group_id, org_id),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)


# ---------------------------------------------------------------------------
# Resolution helpers — used by the LLM/intent path
# ---------------------------------------------------------------------------

def resolve_group(org_id: int,
                  group_id: Optional[int] = None,
                  group_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Find a group by id (preferred) or fuzzy-by-name (case-insensitive)."""
    if group_id:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            set_org_rls(cur, org_id)
            cur.execute(
                "SELECT id, name FROM user_groups WHERE id = %s AND org_id = %s;",
                (group_id, org_id),
            )
            row = cur.fetchone()
            cur.close()
            if row:
                return dict(row)
        finally:
            release_db_connection(conn)

    if group_name:
        return get_group_by_name(org_id, group_name)
    return None
