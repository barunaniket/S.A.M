"""
Bulk task assignment + per-assignee task status.

Routes:
    POST   /api/v1/tasks/bulk-upload         (multipart, ADMIN)
    POST   /api/v1/tasks/manual              (JSON list, ADMIN)
    POST   /api/v1/tasks/confirm/{pending_id}  (commit a pending parse, ADMIN)
    GET    /api/v1/tasks?role=admin|assignee   (list)
    GET    /api/v1/tasks/{id}                  (single)
    PATCH  /api/v1/tasks/{id}                  (mark done / cancel)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from src.api.routes.uploads import _save_upload, persist_pending_upload
from src.services.file_ingestor import parse_file
from src.services.task_extractor import extract_tasks
from src.services.task_service import (
    create_tasks_bulk,
    format_task_message,
    get_task,
    list_tasks_for_assignee,
    list_tasks_for_assigner,
    update_status,
)
from src.services.whatsapp_queue import queue_whatsapp
from src.utils.db_handler import (
    get_db,
    get_db_connection,
    get_user_by_email,
    release_db_connection,
)
from src.utils.rbac import require_roles

logger = logging.getLogger(__name__)
router = APIRouter()


class TaskTuple(BaseModel):
    assignee_name: str
    title: str
    description: Optional[str] = None
    deadline: Optional[datetime] = None


class BulkUploadConfirm(BaseModel):
    tasks: List[TaskTuple]


class StatusUpdate(BaseModel):
    status: str  # "DONE" | "CANCELLED" | "PENDING"


# ---------------------------------------------------------------------------
# Upload + parse
# ---------------------------------------------------------------------------

@router.post(
    "/tasks/bulk-upload",
    dependencies=[Depends(require_roles("ADMIN"))],
)
async def bulk_upload(request: Request, file: UploadFile = File(...)):
    org_id = request.state.org_id
    user_id = request.state.user_id

    saved_path = _save_upload(org_id, file)
    try:
        parsed = parse_file(str(saved_path))
    except ValueError as e:
        try:
            os.remove(saved_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail=str(e)) from e

    text = parsed.get("text") or ""
    extraction = extract_tasks(text)
    tasks = extraction.get("tasks", [])

    upload_id = persist_pending_upload(
        org_id=org_id, user_id=user_id, file_path=str(saved_path),
        parsed={**parsed, "tasks": tasks,
                "needs_review": extraction.get("needs_review", False)},
        parse_kind="tasks",
    )

    return {
        "success":      True,
        "pending_id":   upload_id,
        "kind":         parsed.get("kind"),
        "tasks":        tasks,
        "needs_review": extraction.get("needs_review", False),
    }


@router.get("/tasks/pending/{pending_id}",
            dependencies=[Depends(require_roles("ADMIN"))])
def get_pending_tasks(pending_id: int, request: Request):
    """Read a pending parse so the review page can render it."""
    org_id = request.state.org_id
    user_id = request.state.user_id
    with get_db(org_id) as cur:
        cur.execute(
            """
            SELECT parsed, status FROM pending_uploads
             WHERE id = %s AND uploaded_by = %s AND parse_kind = 'tasks';
            """,
            (pending_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
    parsed = row["parsed"]
    if isinstance(parsed, str):
        parsed = json.loads(parsed)
    return {
        "success": True,
        "tasks": (parsed or {}).get("tasks", []),
        "status": row["status"],
        "needs_review": (parsed or {}).get("needs_review", False),
    }


# ---------------------------------------------------------------------------
# Confirm (with optional caller-edited list)
# ---------------------------------------------------------------------------

@router.post(
    "/tasks/confirm/{pending_id}",
    dependencies=[Depends(require_roles("ADMIN"))],
)
def confirm_tasks(pending_id: int, payload: BulkUploadConfirm, request: Request):
    org_id = request.state.org_id
    user_id = request.state.user_id

    final = [t.model_dump() for t in payload.tasks]
    if not final:
        raise HTTPException(status_code=400, detail="No tasks to send")

    created = create_tasks_bulk(
        org_id=org_id, assigned_by=user_id,
        tasks=final, source_upload_id=pending_id,
        schedule_reminders=True,
    )

    # Personalised kickoff DM via WhatsApp.
    sent = unmatched = 0
    for c in created:
        body = format_task_message(c, kind="assigned")
        target_phone = None
        if c.get("assignee_email"):
            try:
                u = get_user_by_email(c["assignee_email"])
                if u:
                    target_phone = u.get("phone_number")
            except Exception:
                pass
        if target_phone:
            try:
                queue_whatsapp(target_phone, body, metadata={
                    "channel": "task_assignment",
                    "task_id": c["id"],
                    "org_id":  org_id,
                    "user_id": c.get("assignee_id"),
                })
                sent += 1
            except Exception:
                logger.exception("queue_whatsapp failed for task %s", c["id"])
        else:
            unmatched += 1

    # Mark pending_upload executed.
    with get_db(org_id) as cur:
        cur.execute(
            "UPDATE pending_uploads SET status='EXECUTED' "
            "WHERE id = %s AND uploaded_by = %s;",
            (pending_id, user_id),
        )

    return {"success": True, "created": len(created),
            "notified": sent, "unmatched": unmatched}


@router.post(
    "/tasks/manual",
    dependencies=[Depends(require_roles("ADMIN"))],
)
def manual_tasks(payload: BulkUploadConfirm, request: Request):
    org_id = request.state.org_id
    user_id = request.state.user_id
    final = [t.model_dump() for t in payload.tasks]
    if not final:
        raise HTTPException(status_code=400, detail="No tasks to send")

    created = create_tasks_bulk(
        org_id=org_id, assigned_by=user_id, tasks=final,
        schedule_reminders=True,
    )
    return {"success": True, "created": len(created)}


# ---------------------------------------------------------------------------
# Reads + status
# ---------------------------------------------------------------------------

@router.get("/tasks", dependencies=[Depends(require_roles())])
def list_tasks(request: Request, role: str = Query("assignee")):
    user_id = request.state.user_id
    if role == "admin":
        rows = list_tasks_for_assigner(user_id)
    else:
        rows = list_tasks_for_assignee(user_id, include_done=False)
    # JSON-serialise datetimes
    for r in rows:
        for k in ("deadline", "created_at"):
            if r.get(k) is not None and not isinstance(r[k], str):
                r[k] = r[k].isoformat()
    return {"success": True, "tasks": rows}


@router.get("/tasks/{task_id}", dependencies=[Depends(require_roles())])
def get_one(task_id: int, request: Request):
    user_id = request.state.user_id
    org_id = request.state.org_id
    task = get_task(task_id)
    if not task or task.get("org_id") != org_id:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("assignee_id") != user_id and task.get("assigned_by") != user_id:
        raise HTTPException(status_code=403, detail="Not your task")
    for k in ("deadline", "created_at"):
        if task.get(k) is not None and not isinstance(task[k], str):
            task[k] = task[k].isoformat()
    return {"success": True, "task": task}


@router.patch("/tasks/{task_id}", dependencies=[Depends(require_roles())])
def patch_task(task_id: int, payload: StatusUpdate, request: Request):
    user_id = request.state.user_id
    if payload.status not in ("PENDING", "DONE", "CANCELLED"):
        raise HTTPException(status_code=400, detail="Invalid status")
    if not update_status(task_id, payload.status, by_user=user_id):
        raise HTTPException(
            status_code=404,
            detail="Task not found or you don't have permission",
        )
    return {"success": True}
