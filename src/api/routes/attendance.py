"""
Attendance read + override routes.

    GET  /api/v1/attendance               filter by subject/batch/date(range)
    GET  /api/v1/attendance/me            student: my own summary
    POST /api/v1/attendance/{record_id}/override
                                          flip PRESENT/ABSENT (faculty/admin)

Reuses src/services/attendance_query.py and attendance_common.override_attendance.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from src.services import attendance_query
from src.services.attendance_common import override_attendance
from src.utils.db_handler import get_db_connection, release_db_connection
from src.utils.rbac import require_roles

router = APIRouter()


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        raise HTTPException(status_code=422,
                            detail=f"Bad date: {s} (expect YYYY-MM-DD)")


@router.get(
    "/attendance",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN", "SUPER_ADMIN"))],
)
def get_attendance(request: Request,
                   subject: str = Query(..., min_length=1),
                   batch: Optional[str] = None,
                   date: Optional[str] = None,
                   date_from: Optional[str] = None,
                   date_to: Optional[str] = None):
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    result = attendance_query.fetch_sheet(
        org_id=int(org_id),
        subject=subject,
        batch=batch,
        class_date=_parse_date(date),
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
    )
    if not result.get("success"):
        raise HTTPException(status_code=400,
                            detail=result.get("message") or "Lookup failed.")
    # ISO-ify the class_date already done in fetch_sheet
    return {"success": True, "data": result["data"]}


@router.get(
    "/attendance/me",
    dependencies=[Depends(require_roles())],   # any authenticated user
)
def get_my_attendance(request: Request,
                      days: int = Query(90, ge=1, le=365)):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    result = attendance_query.fetch_my_summary(int(user_id), days=days)
    return {"success": True, "data": result["data"]}


class OverridePatch(BaseModel):
    status: str   # "PRESENT" or "ABSENT"


@router.post(
    "/attendance/{record_id}/override",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN", "SUPER_ADMIN"))],
)
def override(record_id: int, payload: OverridePatch, request: Request):
    org_id = getattr(request.state, "org_id", None)
    user_id = getattr(request.state, "user_id", None)
    if not org_id or not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    status = (payload.status or "").upper()
    if status not in ("PRESENT", "ABSENT"):
        raise HTTPException(status_code=422,
                            detail="status must be PRESENT or ABSENT.")

    # Pull the record so we know which student/subject/date to override.
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.id, a.org_id, a.user_id, a.subject, a.class_date,
                   a.session_id, a.source, u.full_name, u.batch
              FROM attendance_records a
              JOIN users u ON u.id = a.user_id
             WHERE a.id = %s
               AND a.org_id = %s
             LIMIT 1;
            """,
            (record_id, org_id),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        release_db_connection(conn)

    if not row:
        raise HTTPException(status_code=404,
                            detail="Attendance record not found.")
    record = dict(row)

    result = override_attendance(
        org_id=int(org_id),
        faculty_id=int(user_id),
        subject=record["subject"],
        batch=record["batch"],
        class_date=record["class_date"],
        student_query=record["full_name"],
        status=status,
        marked_by=int(user_id),
        source=record.get("source") or "manual",
        session_id=record.get("session_id"),
    )
    return {"success": result.get("success", False),
            "message": result.get("message"),
            "data": {k: v for k, v in result.items()
                     if k not in ("success", "message")}}
