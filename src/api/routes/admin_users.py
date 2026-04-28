"""
SUPER_ADMIN user management.

Routes:
    GET   /api/v1/admin/users
    PATCH /api/v1/admin/users/{user_id}    (role, department, phone, full_name)
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.utils.db_handler import get_db_connection, release_db_connection
from src.utils.rbac import KNOWN_ROLES, require_roles

router = APIRouter()


class UserPatch(BaseModel):
    role: Optional[str] = None
    department: Optional[str] = None
    phone_number: Optional[str] = None
    full_name: Optional[str] = None


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
                   is_onboarded, created_at
              FROM users
             WHERE org_id = %s
             ORDER BY full_name NULLS LAST, email;
            """,
            (org_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    finally:
        release_db_connection(conn)
    for r in rows:
        for k in ("created_at",):
            if r.get(k) is not None and not isinstance(r[k], str):
                r[k] = r[k].isoformat()
    return {"success": True, "users": rows}


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
    return {"success": True}
