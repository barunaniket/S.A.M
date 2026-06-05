"""
attendance_query.py
-------------------
Read-path for the v11 `attendance_records` table. Until v13 nothing
queried this table at all — there were write services (attendance_mcq,
attendance_poll, attendance_common.override_attendance) but no
"show me the sheet" path. That gap was the canonical user pain
("bring up the attendance sheet for [class I teach]" → unknown intent).

Public API:

    fetch_sheet(org_id, subject, *, batch=None, class_date=None,
                date_from=None, date_to=None) -> dict
        Faculty/admin: list the present + absent rows for a class day.
        Returns the standard envelope; `data` includes `present`, `absent`,
        and a precomputed `message` for the chat surface.

    fetch_my_summary(user_id, *, days=90) -> dict
        Student: per-subject (present, total, percent) over the last
        `days` days.

    list_class_roster(org_id, batch) -> dict
        Faculty/admin: roster for a batch with last_seen attendance date.

All read-only, RLS-aware via callers passing org_id.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from src.utils.db_handler import get_db_connection, release_db_connection
from src.utils.formatters import (
    format_attendance_sheet,
    format_class_roster,
    format_my_attendance,
)

logger = logging.getLogger(__name__)


def fetch_sheet(org_id: int, subject: str,
                *, batch: Optional[str] = None,
                class_date: Optional[date] = None,
                date_from: Optional[date] = None,
                date_to: Optional[date] = None) -> Dict[str, Any]:
    """
    Faculty/admin: pull attendance for one (subject, batch) on a date or
    over a date range. When neither is given, defaults to today.

    Returns:
        {
          success: True,
          data: {
            subject, batch, class_date,
            present: [{user_id, full_name, score, overridden}, ...],
            absent:  [{user_id, full_name, overridden}, ...],
            total: int,
          },
          message: <Telegram-ready HTML>,
        }
    """
    if not subject:
        return {"success": False,
                "needs_clarification": True,
                "message": "Which subject? e.g. <i>show CS201 attendance</i>"}

    if class_date is None and date_from is None and date_to is None:
        class_date = date.today()

    where = ["a.org_id = %s", "LOWER(a.subject) = LOWER(%s)"]
    params: List[Any] = [org_id, subject]

    if class_date is not None:
        where.append("a.class_date = %s")
        params.append(class_date)
    else:
        if date_from is not None:
            where.append("a.class_date >= %s")
            params.append(date_from)
        if date_to is not None:
            where.append("a.class_date <= %s")
            params.append(date_to)

    if batch:
        where.append("u.batch = %s")
        params.append(batch)

    sql = f"""
        SELECT a.id, a.user_id, a.subject, a.class_date, a.status,
               a.score, a.overridden, a.source,
               u.full_name, u.batch
          FROM attendance_records a
          JOIN users u ON u.id = a.user_id
         WHERE {" AND ".join(where)}
         ORDER BY a.class_date DESC, u.full_name ASC;
    """

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    finally:
        release_db_connection(conn)

    present = [r for r in rows if r["status"] == "PRESENT"]
    absent = [r for r in rows if r["status"] == "ABSENT"]

    display_date = class_date or (date_to or date.today())
    msg = format_attendance_sheet(
        subject=subject,
        batch=batch,
        class_date=display_date,
        present=present,
        absent=absent,
    )

    return {
        "success": True,
        "data": {
            "subject": subject,
            "batch": batch,
            "class_date": display_date.isoformat(),
            "present": present,
            "absent": absent,
            "total": len(rows),
        },
        "message": msg,
    }


def fetch_my_summary(user_id: int, *, days: int = 90) -> Dict[str, Any]:
    """
    Student-facing: per-subject (present, total, percent) over the last
    `days` days. Single SQL with conditional aggregation.
    """
    cutoff = date.today() - timedelta(days=days)

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.full_name FROM users u WHERE u.id = %s LIMIT 1;
            """,
            (user_id,),
        )
        urow = cur.fetchone()

        cur.execute(
            """
            SELECT subject,
                   COUNT(*)                                AS total,
                   COUNT(*) FILTER (WHERE status='PRESENT') AS present,
                   MAX(class_date)                         AS last_class
              FROM attendance_records
             WHERE user_id    = %s
               AND class_date >= %s
             GROUP BY subject
             ORDER BY subject;
            """,
            (user_id, cutoff),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    finally:
        release_db_connection(conn)

    student_name = (urow or {}).get("full_name") or "Student"
    summary: List[Dict[str, Any]] = []
    for r in rows:
        total = int(r["total"] or 0)
        present = int(r["present"] or 0)
        pct = (100.0 * present / total) if total else 0.0
        summary.append({
            "subject": r["subject"],
            "total": total,
            "present": present,
            "percent": pct,
            "last_class": r["last_class"].isoformat() if r["last_class"] else None,
        })

    msg = format_my_attendance(student_name=student_name, summary=summary)
    return {
        "success": True,
        "data": {"student_name": student_name, "summary": summary,
                 "days": days},
        "message": msg,
    }


def list_class_roster(org_id: int, batch: str) -> Dict[str, Any]:
    """
    Faculty/admin: roster for a batch with last_seen attendance date.
    Used by the `list_class_roster` intent.
    """
    if not batch:
        return {"success": False,
                "needs_clarification": True,
                "message": ("Which batch? e.g. "
                            "<i>list students in CSE-3A</i>")}

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.id, u.full_name, u.email, u.batch,
                   u.telegram_chat_id, u.phone_number,
                   MAX(a.class_date) AS last_seen
              FROM users u
              LEFT JOIN attendance_records a
                ON a.user_id = u.id AND a.status = 'PRESENT'
             WHERE u.org_id = %s
               AND u.role   = 'STUDENT'
               AND u.batch  = %s
             GROUP BY u.id
             ORDER BY u.full_name;
            """,
            (org_id, batch),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    finally:
        release_db_connection(conn)

    msg = format_class_roster(batch=batch, rows=rows)
    return {
        "success": True,
        "data": {"batch": batch, "students": rows, "count": len(rows)},
        "message": msg,
    }
