"""
SUPER_ADMIN member management.

Routes:
    GET    /api/v1/admin/users
    POST   /api/v1/admin/users                     create user (+ optional timetable + groups)
    PATCH  /api/v1/admin/users/{user_id}           update profile fields
    DELETE /api/v1/admin/users/{user_id}           remove user (CASCADE)
    GET    /api/v1/admin/users/{user_id}/timetable read someone else's timetable
    POST   /api/v1/admin/users/{user_id}/timetable replace someone's timetable
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.services import group_service
from src.services.timetable_service import (
    list_entries_for_user,
    upsert_entries,
)
from src.utils.db_handler import get_db_connection, release_db_connection
from src.utils.rbac import KNOWN_ROLES, require_roles

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TimetableEntryIn(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: str        # "HH:MM" or "HH:MM:SS"
    end_time:   str
    subject: Optional[str] = None
    room:    Optional[str] = None
    batch:   Optional[str] = None


class UserCreate(BaseModel):
    email: str
    full_name: str
    role: str
    phone_number:    Optional[str] = None
    department:      Optional[str] = None
    office_location: Optional[str] = None   # staff room (faculty/admin)
    batch:           Optional[str] = None   # student class
    timetable: Optional[List[TimetableEntryIn]] = None
    group_names: Optional[List[str]] = None  # auto-add to these groups


class UserPatch(BaseModel):
    role:            Optional[str] = None
    department:      Optional[str] = None
    phone_number:    Optional[str] = None
    full_name:       Optional[str] = None
    office_location: Optional[str] = None
    batch:           Optional[str] = None


class TimetablePut(BaseModel):
    entries: List[TimetableEntryIn]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_group(org_id: int, name: str, created_by: int) -> int:
    """Find a user_groups row by name, create it if missing. Returns id."""
    name = (name or "").strip()
    if not name:
        raise ValueError("group name cannot be empty")
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM user_groups WHERE org_id = %s AND LOWER(name) = LOWER(%s) LIMIT 1;",
            (org_id, name),
        )
        row = cur.fetchone()
        if row:
            cur.close()
            return int(row["id"])
        cur.execute(
            """
            INSERT INTO user_groups (org_id, name, description, created_by)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """,
            (org_id, name, None, created_by),
        )
        gid = int(cur.fetchone()["id"])
        conn.commit()
        cur.close()
        return gid
    except Exception:
        conn.rollback()
        raise
    finally:
        release_db_connection(conn)


def _serialize_user(r: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(r)
    for k in ("created_at", "updated_at"):
        v = out.get(k)
        if v is not None and not isinstance(v, str):
            out[k] = v.isoformat()
    return out


# ---------------------------------------------------------------------------
# List + read
# ---------------------------------------------------------------------------

@router.get(
    "/admin/users",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def list_users(request: Request):
    org_id = request.state.org_id
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, email, full_name, role, department, phone_number,
                   office_location, batch, is_onboarded, created_at
              FROM users
             WHERE org_id = %s
             ORDER BY role, full_name NULLS LAST, email;
            """,
            (org_id,),
        )
        rows = [_serialize_user(r) for r in cur.fetchall()]
        cur.close()
    finally:
        release_db_connection(conn)
    return {"success": True, "data": {"users": rows}}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@router.post(
    "/admin/users",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def create_user(payload: UserCreate, request: Request):
    org_id = request.state.org_id
    actor_id = request.state.user_id

    if payload.role not in KNOWN_ROLES:
        raise HTTPException(status_code=400,
                            detail=f"Unknown role {payload.role!r}")

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # Existence guard: same email already in any org → reject.
        cur.execute("SELECT id FROM users WHERE email = %s LIMIT 1;",
                    (payload.email,))
        if cur.fetchone():
            cur.close()
            raise HTTPException(status_code=409,
                                detail=f"User with email {payload.email} already exists")

        cur.execute(
            """
            INSERT INTO users
                (org_id, email, full_name, role, phone_number,
                 department, office_location, batch, is_onboarded)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE)
            RETURNING id, email, full_name, role, department,
                      phone_number, office_location, batch, created_at;
            """,
            (
                org_id, payload.email, payload.full_name, payload.role,
                payload.phone_number, payload.department,
                payload.office_location, payload.batch,
            ),
        )
        new_user = dict(cur.fetchone())
        new_user_id = int(new_user["id"])
        conn.commit()
        cur.close()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        release_db_connection(conn)

    # Optional: timetable
    timetable_count = 0
    if payload.timetable:
        try:
            timetable_count = upsert_entries(
                org_id=org_id, user_id=new_user_id,
                entries=[e.model_dump() for e in payload.timetable],
                source="super_admin",
                replace_all=True,
            )
        except Exception as e:
            logger.exception("Failed to write timetable for new user %s", new_user_id)
            # Non-fatal — caller can retry the timetable via the /timetable
            # endpoint. We surface the error in the response.
            return {"success": True, "user": _serialize_user(new_user),
                    "timetable_entries": 0,
                    "warnings": [f"timetable save failed: {e}"]}

    # Optional: auto-add to groups
    groups_added: List[str] = []
    if payload.group_names:
        for raw in payload.group_names:
            name = (raw or "").strip()
            if not name:
                continue
            try:
                gid = _ensure_group(org_id, name, actor_id)
                group_service.add_member(org_id, gid, new_user_id)
                groups_added.append(name)
            except Exception:
                logger.exception("Failed to add user %s to group %s", new_user_id, name)

    return {
        "success": True,
        "data": {
            "user": _serialize_user(new_user),
            "timetable_entries": timetable_count,
            "groups_added": groups_added,
        },
    }


# ---------------------------------------------------------------------------
# Patch
# ---------------------------------------------------------------------------

@router.patch(
    "/admin/users/{user_id}",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def patch_user(user_id: int, payload: UserPatch, request: Request):
    org_id = request.state.org_id

    if payload.role and payload.role not in KNOWN_ROLES:
        raise HTTPException(status_code=400, detail=f"Unknown role {payload.role!r}")

    fields: List[str] = []
    params: List = []
    for col, val in (
        ("role", payload.role),
        ("department", payload.department),
        ("phone_number", payload.phone_number),
        ("full_name", payload.full_name),
        ("office_location", payload.office_location),
        ("batch", payload.batch),
    ):
        if val is not None:
            fields.append(f"{col} = %s")
            params.append(val)
    if not fields:
        raise HTTPException(status_code=400, detail="Nothing to update")

    params.extend([user_id, org_id])
    sql = f"UPDATE users SET {', '.join(fields)}, updated_at = NOW() " \
          f"WHERE id = %s AND org_id = %s;"

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, tuple(params))
        affected = cur.rowcount
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        release_db_connection(conn)

    if not affected:
        raise HTTPException(status_code=404, detail="User not found in your org")
    return {"success": True, "data": None}


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete(
    "/admin/users/{user_id}",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def delete_user(user_id: int, request: Request):
    org_id = request.state.org_id
    actor_id = request.state.user_id

    if user_id == actor_id:
        raise HTTPException(
            status_code=400,
            detail="Refusing to delete yourself — that would lock the org out.",
        )

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM users WHERE id = %s AND org_id = %s;",
            (user_id, org_id),
        )
        deleted = cur.rowcount
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        release_db_connection(conn)

    if not deleted:
        raise HTTPException(status_code=404, detail="User not found in your org")
    return {"success": True, "data": {"deleted_id": user_id}}


# ---------------------------------------------------------------------------
# Timetable for any user (super-admin maintenance surface)
# ---------------------------------------------------------------------------

@router.get(
    "/admin/users/{user_id}/timetable",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def get_user_timetable(user_id: int, request: Request):
    entries = list_entries_for_user(user_id)
    # Trim TIME columns to "HH:MM:SS" strings so JSON encoding doesn't choke.
    for e in entries:
        for k in ("start_time", "end_time"):
            v = e.get(k)
            if v is not None and not isinstance(v, str):
                e[k] = v.strftime("%H:%M:%S") if hasattr(v, "strftime") else str(v)
    return {"success": True, "data": {"entries": entries}}


@router.post(
    "/admin/users/{user_id}/timetable",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def put_user_timetable(user_id: int, payload: TimetablePut, request: Request):
    org_id = request.state.org_id
    rows = upsert_entries(
        org_id=org_id, user_id=user_id,
        entries=[e.model_dump() for e in payload.entries],
        source="super_admin", replace_all=True,
    )
    return {"success": True, "data": {"saved": rows}}
