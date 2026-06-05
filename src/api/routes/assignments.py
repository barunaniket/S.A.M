"""
Faculty / admin assignment routes.

    GET  /api/v1/assignments/mine                  list-with-counts
    GET  /api/v1/assignments/{assignment_id}       single + meta
    GET  /api/v1/assignments/{assignment_id}/submissions
                                                   submitted + missing buckets

Student-side flows (submit/discard/list_open) stay in the Telegram
orchestrator + assignment_service for now — these routes are read-mostly,
faculty-facing. RBAC: FACULTY|ADMIN|SUPER_ADMIN.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from src.services import assignment_service
from src.utils.db_handler import get_db_connection, release_db_connection
from src.utils.rbac import require_roles

router = APIRouter()


def _resolve_caller(request: Request) -> dict:
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    if not user_id or not org_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return {"user_id": user_id, "org_id": org_id}


@router.get(
    "/assignments/mine",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN", "SUPER_ADMIN"))],
)
def list_mine(request: Request):
    me = _resolve_caller(request)
    rows = assignment_service.list_open_for_faculty(
        org_id=me["org_id"], faculty_id=me["user_id"],
    )
    # Coerce datetimes to ISO for JSON serialisation.
    for r in rows:
        for k in ("due_at", "created_at"):
            v = r.get(k)
            if v is not None and hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    return {"success": True, "data": rows}


@router.get(
    "/assignments/{assignment_id}",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN", "SUPER_ADMIN"))],
)
def get_one(assignment_id: int, request: Request):
    me = _resolve_caller(request)
    a = assignment_service.get_assignment(assignment_id)
    if not a or a.get("org_id") != me["org_id"]:
        raise HTTPException(status_code=404, detail="Assignment not found.")
    for k in ("due_at", "created_at"):
        v = a.get(k)
        if v is not None and hasattr(v, "isoformat"):
            a[k] = v.isoformat()
    return {"success": True, "data": a}


@router.get(
    "/assignments/{assignment_id}/submissions",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN", "SUPER_ADMIN"))],
)
def list_submissions(assignment_id: int, request: Request):
    me = _resolve_caller(request)
    a = assignment_service.get_assignment(assignment_id)
    if not a or a.get("org_id") != me["org_id"]:
        raise HTTPException(status_code=404, detail="Assignment not found.")

    result = assignment_service.submissions_for_assignment(assignment_id)
    if not result.get("success"):
        raise HTTPException(status_code=500,
                            detail=result.get("message") or "Lookup failed.")

    data = result["data"]
    for r in data["submitted"]:
        for k in ("submitted_at", "confirmed_at"):
            v = r.get(k)
            if v is not None and hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    a = data["assignment"]
    for k in ("due_at", "created_at"):
        v = a.get(k)
        if v is not None and hasattr(v, "isoformat"):
            a[k] = v.isoformat()
    return {"success": True, "data": data}
