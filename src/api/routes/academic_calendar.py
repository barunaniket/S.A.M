"""
Academic-calendar management (SUPER_ADMIN only for writes).

Routes:
    POST   /api/v1/academic/upload          (multipart file)
    POST   /api/v1/academic/manual          (JSON events)
    GET    /api/v1/academic/events
    DELETE /api/v1/academic/events/{id}
"""

from __future__ import annotations

import logging
import os
from datetime import date as _date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from src.api.routes.uploads import _save_upload, persist_pending_upload
from src.services.academic_calendar import (
    delete_event,
    extract_events_from_text,
    import_events,
    list_events,
)
from src.services.file_ingestor import parse_file
from src.utils.rbac import require_roles

logger = logging.getLogger(__name__)
router = APIRouter()


class AcademicEventIn(BaseModel):
    kind: str  # HOLIDAY | EXAM | BREAK | EVENT
    title: str
    start_date: _date
    end_date: _date


class ManualPayload(BaseModel):
    events: List[AcademicEventIn]
    replace_overlapping: bool = False


# ---------------------------------------------------------------------------
# Upload (PDF/Excel/text/docx) — extract via LLM, return for review
# ---------------------------------------------------------------------------

@router.post(
    "/academic/upload",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
async def upload_calendar(request: Request, file: UploadFile = File(...)):
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
    events = extract_events_from_text(text)

    upload_id = persist_pending_upload(
        org_id=org_id, user_id=user_id, file_path=str(saved_path),
        parsed={**parsed, "events": [
            {**e, "start_date": e["start_date"].isoformat(),
             "end_date": e["end_date"].isoformat()}
            for e in events
        ]},
        parse_kind="academic_calendar",
    )

    return {
        "success":    True,
        "pending_id": upload_id,
        "events": [
            {**e, "start_date": e["start_date"].isoformat(),
             "end_date": e["end_date"].isoformat()}
            for e in events
        ],
        "needs_review": not events,
    }


# ---------------------------------------------------------------------------
# Confirm + manual entry
# ---------------------------------------------------------------------------

@router.post(
    "/academic/confirm/{pending_id}",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def confirm_calendar(pending_id: int, payload: ManualPayload, request: Request):
    org_id = request.state.org_id
    user_id = request.state.user_id

    rows = import_events(
        org_id=org_id,
        events=[e.model_dump() for e in payload.events],
        uploaded_by=user_id,
        source_upload_id=pending_id,
        replace_overlapping=payload.replace_overlapping,
    )
    return {"success": True, "saved": rows}


@router.post(
    "/academic/manual",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def manual_calendar(payload: ManualPayload, request: Request):
    org_id = request.state.org_id
    user_id = request.state.user_id
    rows = import_events(
        org_id=org_id,
        events=[e.model_dump() for e in payload.events],
        uploaded_by=user_id,
        replace_overlapping=payload.replace_overlapping,
    )
    return {"success": True, "saved": rows}


# ---------------------------------------------------------------------------
# Reads / deletes
# ---------------------------------------------------------------------------

@router.get("/academic/events", dependencies=[Depends(require_roles())])
def get_events(request: Request,
               start: Optional[_date] = None,
               end: Optional[_date] = None):
    org_id = request.state.org_id
    return {
        "success": True,
        "events": [
            {**e,
             "start_date": e["start_date"].isoformat(),
             "end_date": e["end_date"].isoformat(),
             "created_at": e["created_at"].isoformat() if e.get("created_at") else None}
            for e in list_events(org_id, start=start, end=end)
        ],
    }


@router.delete(
    "/academic/events/{event_id}",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def delete(event_id: int, request: Request):
    org_id = request.state.org_id
    if not delete_event(org_id, event_id):
        raise HTTPException(status_code=404, detail="Event not found")
    return {"success": True, "deleted": event_id}
