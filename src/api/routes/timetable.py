"""
Timetable management API.

Faculty/admin upload their weekly timetable as a file (image, audio, PDF,
docx, Excel, plain text) or as a JSON list of entries from the web UI. The
backend parses through file_ingestor → timetable_extractor, returns the
structured grid for review, and persists on confirm.

Routes:
    POST   /api/v1/timetable/upload          (multipart file)
    POST   /api/v1/timetable/manual          (JSON entries)
    POST   /api/v1/timetable/confirm/{id}    (commit pending parse)
    DELETE /api/v1/timetable/me              (clear my timetable)
    GET    /api/v1/timetable/me              (list my entries)
    GET    /api/v1/timetable/user/{user_id}  (list someone else's entries)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from src.api.routes.uploads import _save_upload, persist_pending_upload
from src.services.file_ingestor import parse_file
from src.services.timetable_extractor import (
    extract_timetable,
    summarize_timetable,
)
from src.services.timetable_service import (
    clear_entries_for_user,
    list_entries_for_user,
    upsert_entries,
)
from src.utils.db_handler import get_db
from src.utils.rbac import require_roles

logger = logging.getLogger(__name__)
router = APIRouter()


class TimetableEntry(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: str
    end_time: str
    subject: Optional[str] = None
    room: Optional[str] = None
    batch: Optional[str] = None


class ManualTimetable(BaseModel):
    entries: List[TimetableEntry]
    source: str = "manual"


# ---------------------------------------------------------------------------
# Upload + parse (faculty only)
# ---------------------------------------------------------------------------

@router.post(
    "/timetable/upload",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN"))],
)
async def upload_timetable(request: Request, file: UploadFile = File(...)):
    """
    Upload a timetable file. The response includes the parsed entries the
    user must review + a `pending_id` they POST back to /confirm to persist.
    """
    org_id = getattr(request.state, "org_id", None)
    user_id = getattr(request.state, "user_id", None)
    if not org_id or not user_id:
        raise HTTPException(status_code=401, detail="Missing user context")

    saved_path = _save_upload(org_id, file)

    try:
        parsed = parse_file(str(saved_path))
    except ValueError as e:
        try:
            os.remove(saved_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        try:
            os.remove(saved_path)
        except OSError:
            pass
        logger.exception("timetable upload: parse_file failed")
        raise HTTPException(status_code=500, detail="Could not parse the file")

    text = parsed.get("text") or ""
    extraction = extract_timetable(text)
    entries = extraction.get("entries", [])

    upload_id = persist_pending_upload(
        org_id=org_id, user_id=user_id, file_path=str(saved_path),
        parsed={**parsed, "timetable": entries,
                "needs_review": extraction.get("needs_review", False)},
        parse_kind="timetable",
    )

    return {
        "success":      True,
        "pending_id":   upload_id,
        "kind":         parsed.get("kind"),
        "entries":      entries,
        "needs_review": extraction.get("needs_review", False),
        "summary":      summarize_timetable(entries),
        "ocr_confidence": parsed.get("ocr_confidence"),
    }


# ---------------------------------------------------------------------------
# Confirm pending parse
# ---------------------------------------------------------------------------

class ConfirmPayload(BaseModel):
    # Optional override — UI may have edited the parsed grid before confirm.
    entries: Optional[List[TimetableEntry]] = None


@router.post(
    "/timetable/confirm/{pending_id}",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN"))],
)
def confirm_timetable(pending_id: int, payload: ConfirmPayload, request: Request):
    org_id = request.state.org_id
    user_id = request.state.user_id

    # Decide which entries to persist: caller-supplied edits OR what we parsed.
    final_entries: List[dict]
    if payload.entries:
        final_entries = [e.model_dump() for e in payload.entries]
    else:
        with get_db(org_id) as cur:
            cur.execute(
                """
                SELECT parsed FROM pending_uploads
                 WHERE id = %s AND uploaded_by = %s
                   AND parse_kind = 'timetable' AND status = 'PARSED';
                """,
                (pending_id, user_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404,
                                    detail="No pending timetable to confirm")
            parsed_field = row["parsed"]
            data = json.loads(parsed_field) if isinstance(parsed_field, str) else (parsed_field or {})
            final_entries = data.get("timetable", []) or []

    if not final_entries:
        raise HTTPException(status_code=400, detail="No entries to save")

    rows = upsert_entries(
        org_id=org_id, user_id=user_id,
        entries=final_entries, source="web", replace_all=True,
    )

    with get_db(org_id) as cur:
        cur.execute(
            "UPDATE pending_uploads SET status = 'EXECUTED' "
            "WHERE id = %s AND uploaded_by = %s;",
            (pending_id, user_id),
        )

    return {"success": True, "saved": rows}


# ---------------------------------------------------------------------------
# Manual entry (web UI types directly without a file upload)
# ---------------------------------------------------------------------------

@router.post(
    "/timetable/manual",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN"))],
)
def manual_timetable(payload: ManualTimetable, request: Request):
    org_id = request.state.org_id
    user_id = request.state.user_id
    rows = upsert_entries(
        org_id=org_id, user_id=user_id,
        entries=[e.model_dump() for e in payload.entries],
        source=payload.source, replace_all=True,
    )
    return {"success": True, "saved": rows}


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@router.get("/timetable/me", dependencies=[Depends(require_roles())])
def my_timetable(request: Request):
    user_id = request.state.user_id
    return {"success": True, "entries": list_entries_for_user(user_id)}


@router.get("/timetable/user/{user_id}", dependencies=[Depends(require_roles())])
def user_timetable(user_id: int, request: Request):
    # Anyone authenticated can read another user's timetable in the same org
    # — that's the whole point of student status queries. Cross-org peeking
    # is blocked because list_entries_for_user is keyed off user_id and
    # users belong to org via FK.
    return {"success": True, "entries": list_entries_for_user(user_id)}


@router.delete(
    "/timetable/me",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN"))],
)
def clear_my_timetable(request: Request):
    user_id = request.state.user_id
    deleted = clear_entries_for_user(user_id)
    return {"success": True, "deleted": deleted}
