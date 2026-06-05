"""
SUPER_ADMIN audit log reads.

Three endpoints over two existing tables (conversation_log + whatsapp_audit):

    GET /api/v1/admin/audit                  union, newest-first
    GET /api/v1/admin/audit/conversations    conversation_log only
    GET /api/v1/admin/audit/whatsapp         whatsapp_audit only

All accept query params: user_id, channel, since (ISO), q (substring search),
limit (≤200), offset.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from src.utils.db_handler import get_db_connection, release_db_connection
from src.utils.rbac import require_roles

router = APIRouter()


_MAX_LIMIT = 200


def _isoify(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for r in rows:
        v = r.get("created_at")
        if v is not None and not isinstance(v, str):
            r["created_at"] = v.isoformat()
    return rows


@router.get(
    "/admin/audit/conversations",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def conversations(
    request: Request,
    user_id: Optional[int] = Query(None),
    channel: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    org_id = request.state.org_id

    sql = [
        "SELECT cl.id, cl.channel, cl.role, cl.content, cl.intent, cl.metadata,",
        "       cl.created_at, cl.user_id, u.full_name AS user_name, u.email AS user_email",
        "  FROM conversation_log cl",
        "  LEFT JOIN users u ON u.id = cl.user_id",
        " WHERE (cl.org_id = %s OR cl.user_id IN (SELECT id FROM users WHERE org_id = %s))",
    ]
    params: List[Any] = [org_id, org_id]

    if user_id is not None:
        sql.append("AND cl.user_id = %s")
        params.append(user_id)
    if channel:
        sql.append("AND cl.channel = %s")
        params.append(channel)
    if since:
        sql.append("AND cl.created_at >= %s")
        params.append(since)
    if q:
        sql.append("AND cl.content ILIKE %s")
        params.append(f"%{q}%")

    sql.append("ORDER BY cl.created_at DESC")
    sql.append("LIMIT %s OFFSET %s")
    params.extend([limit, offset])

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(" ".join(sql), tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    finally:
        release_db_connection(conn)
    return {"success": True, "data": _isoify(rows)}


@router.get(
    "/admin/audit/whatsapp",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def whatsapp(
    request: Request,
    user_id: Optional[int] = Query(None),
    direction: Optional[str] = Query(None),
    msg_type: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    org_id = request.state.org_id

    sql = [
        "SELECT wa.id, wa.phone, wa.direction, wa.msg_type, wa.body,",
        "       wa.intent, wa.metadata, wa.created_at, wa.user_id,",
        "       u.full_name AS user_name, u.email AS user_email",
        "  FROM whatsapp_audit wa",
        "  LEFT JOIN users u ON u.id = wa.user_id",
        " WHERE (wa.org_id = %s OR wa.user_id IN (SELECT id FROM users WHERE org_id = %s))",
    ]
    params: List[Any] = [org_id, org_id]

    if user_id is not None:
        sql.append("AND wa.user_id = %s")
        params.append(user_id)
    if direction:
        sql.append("AND wa.direction = %s")
        params.append(direction)
    if msg_type:
        sql.append("AND wa.msg_type = %s")
        params.append(msg_type)
    if since:
        sql.append("AND wa.created_at >= %s")
        params.append(since)
    if q:
        sql.append("AND wa.body ILIKE %s")
        params.append(f"%{q}%")

    sql.append("ORDER BY wa.created_at DESC")
    sql.append("LIMIT %s OFFSET %s")
    params.extend([limit, offset])

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(" ".join(sql), tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    finally:
        release_db_connection(conn)
    return {"success": True, "data": _isoify(rows)}


@router.get(
    "/admin/audit",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def union(
    request: Request,
    user_id: Optional[int] = Query(None),
    channel: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
):
    """
    Convenience read that interleaves conversation_log + whatsapp_audit
    by created_at. Each row gains a `source` field ("conversation"/"whatsapp")
    so the UI can render appropriate columns.
    """
    org_id = request.state.org_id

    # Build two SELECTs with a `source` literal column, UNION ALL, then sort.
    conv_sql = [
        "SELECT 'conversation' AS source, cl.id, cl.channel,",
        "       cl.role AS role_or_direction,",
        "       NULL::TEXT AS msg_type,",
        "       cl.content AS body, cl.intent, cl.created_at,",
        "       cl.user_id, u.full_name AS user_name, u.email AS user_email,",
        "       NULL::TEXT AS phone, cl.metadata",
        "  FROM conversation_log cl",
        "  LEFT JOIN users u ON u.id = cl.user_id",
        " WHERE (cl.org_id = %s OR cl.user_id IN (SELECT id FROM users WHERE org_id = %s))",
    ]
    conv_params: List[Any] = [org_id, org_id]
    if user_id is not None:
        conv_sql.append("AND cl.user_id = %s")
        conv_params.append(user_id)
    if channel:
        conv_sql.append("AND cl.channel = %s")
        conv_params.append(channel)
    if since:
        conv_sql.append("AND cl.created_at >= %s")
        conv_params.append(since)
    if q:
        conv_sql.append("AND cl.content ILIKE %s")
        conv_params.append(f"%{q}%")

    wa_sql = [
        "SELECT 'whatsapp' AS source, wa.id, 'whatsapp'::VARCHAR AS channel,",
        "       wa.direction AS role_or_direction,",
        "       wa.msg_type AS msg_type,",
        "       wa.body, wa.intent, wa.created_at,",
        "       wa.user_id, u.full_name AS user_name, u.email AS user_email,",
        "       wa.phone, wa.metadata",
        "  FROM whatsapp_audit wa",
        "  LEFT JOIN users u ON u.id = wa.user_id",
        " WHERE (wa.org_id = %s OR wa.user_id IN (SELECT id FROM users WHERE org_id = %s))",
    ]
    wa_params: List[Any] = [org_id, org_id]
    if user_id is not None:
        wa_sql.append("AND wa.user_id = %s")
        wa_params.append(user_id)
    # When the caller filters channel=whatsapp we keep WhatsApp rows; when they
    # filter to telegram/system we drop the whatsapp_audit branch entirely.
    drop_wa = bool(channel) and channel != "whatsapp"
    if since:
        wa_sql.append("AND wa.created_at >= %s")
        wa_params.append(since)
    if q:
        wa_sql.append("AND wa.body ILIKE %s")
        wa_params.append(f"%{q}%")

    if drop_wa:
        full_sql = " ".join(conv_sql) + " ORDER BY created_at DESC LIMIT %s"
        params = conv_params + [limit]
    else:
        full_sql = (
            "(" + " ".join(conv_sql) + ") UNION ALL (" + " ".join(wa_sql) + ") "
            "ORDER BY created_at DESC LIMIT %s"
        )
        params = conv_params + wa_params + [limit]

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(full_sql, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    finally:
        release_db_connection(conn)
    return {"success": True, "data": _isoify(rows)}
