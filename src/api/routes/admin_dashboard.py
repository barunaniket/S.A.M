"""
SUPER_ADMIN org overview / dashboard.

GET /api/v1/admin/dashboard — single aggregate call so the panel can render
in one round-trip. Cheap reads only; no LLM, no Calendar API hits.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

from src.utils.db_handler import get_db_connection, release_db_connection
from src.utils.rbac import require_roles

logger = logging.getLogger(__name__)
router = APIRouter()


def _scalar(cur, sql: str, params: tuple = ()) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        return 0
    # cur uses RealDictCursor; first value is in row[<first_key>]
    return int(next(iter(row.values())) or 0)


@router.get(
    "/admin/dashboard",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def dashboard(request: Request) -> Dict[str, Any]:
    org_id = request.state.org_id
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = today_start + timedelta(days=1)
    weekday = today.weekday()  # 0=Mon … 6=Sun

    out: Dict[str, Any] = {
        "users":              {},
        "groups":             0,
        "today":              {},
        "pending_bookings":   0,
        "academic_events_30d": 0,
        "recent":             [],
    }

    conn = get_db_connection()
    try:
        cur = conn.cursor()

        # Users by role
        cur.execute(
            """
            SELECT role, COUNT(*) AS n
              FROM users
             WHERE org_id = %s
             GROUP BY role;
            """,
            (org_id,),
        )
        users_by_role = {r["role"]: int(r["n"]) for r in cur.fetchall() if r.get("role")}
        # Ensure all canonical roles appear (even with 0)
        for r in ("FACULTY", "ADMIN", "STUDENT", "SUPER_ADMIN", "BOOKING_AUTHORITY"):
            users_by_role.setdefault(r, 0)
        out["users"] = users_by_role

        # Groups
        out["groups"] = _scalar(
            cur, "SELECT COUNT(*) AS n FROM user_groups WHERE org_id = %s;",
            (org_id,),
        )

        # Today: meetings (Google Calendar table)
        try:
            out["today"]["meetings"] = _scalar(
                cur,
                """
                SELECT COUNT(*) AS n FROM meetings
                 WHERE start_time >= %s AND start_time < %s;
                """,
                (today_start, today_end),
            )
        except Exception:
            out["today"]["meetings"] = 0

        # Today: tasks due
        try:
            out["today"]["tasks_due"] = _scalar(
                cur,
                """
                SELECT COUNT(*) AS n FROM tasks
                 WHERE org_id = %s
                   AND deadline >= %s AND deadline < %s
                   AND status = 'PENDING';
                """,
                (org_id, today_start, today_end),
            )
        except Exception:
            out["today"]["tasks_due"] = 0

        # Today: classes (timetable_entries)
        try:
            out["today"]["classes"] = _scalar(
                cur,
                """
                SELECT COUNT(*) AS n FROM timetable_entries
                 WHERE org_id = %s AND day_of_week = %s;
                """,
                (org_id, weekday),
            )
        except Exception:
            out["today"]["classes"] = 0

        # Pending room bookings
        try:
            out["pending_bookings"] = _scalar(
                cur,
                """
                SELECT COUNT(*) AS n FROM room_bookings
                 WHERE org_id = %s AND status = 'PENDING';
                """,
                (org_id,),
            )
        except Exception:
            out["pending_bookings"] = 0

        # Academic events in next 30 days
        try:
            out["academic_events_30d"] = _scalar(
                cur,
                """
                SELECT COUNT(*) AS n FROM academic_events
                 WHERE org_id = %s
                   AND end_date >= %s
                   AND start_date <= %s;
                """,
                (org_id, today, today + timedelta(days=30)),
            )
        except Exception:
            out["academic_events_30d"] = 0

        # Recent activity (last 10 conversation_log lines)
        try:
            cur.execute(
                """
                SELECT cl.channel, cl.role, cl.content, cl.intent,
                       cl.created_at, cl.user_id, u.full_name AS user_name
                  FROM conversation_log cl
                  LEFT JOIN users u ON u.id = cl.user_id
                 WHERE cl.org_id = %s OR cl.user_id IN
                       (SELECT id FROM users WHERE org_id = %s)
                 ORDER BY cl.created_at DESC
                 LIMIT 10;
                """,
                (org_id, org_id),
            )
            recent = []
            for r in cur.fetchall():
                content = r.get("content") or ""
                if len(content) > 140:
                    content = content[:137] + "…"
                recent.append({
                    "channel": r.get("channel"),
                    "role": r.get("role"),
                    "content": content,
                    "intent": r.get("intent"),
                    "user_id": r.get("user_id"),
                    "user_name": r.get("user_name"),
                    "created_at": r["created_at"].isoformat()
                                  if r.get("created_at") else None,
                })
            out["recent"] = recent
        except Exception as e:
            logger.warning("dashboard: recent activity query failed: %s", e)
            out["recent"] = []

        cur.close()
    finally:
        release_db_connection(conn)

    return {"success": True, "data": out}
