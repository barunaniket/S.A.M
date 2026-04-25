"""
POST /api/v1/uploads
--------------------
Faculty-facing file upload. Persists the file under data/uploads/{org_id}/,
parses it, stores a `pending_uploads` row, and returns a summary the caller
(WhatsApp orchestrator or frontend) can echo back to the user.
"""

import json
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from src.services.file_ingestor import (
    SUPPORTED_EXTS,
    extract_attendees,
    extract_meeting_metadata,
    parse_file,
    summarize,
    summarize_meeting,
)
from src.utils.config_loader import Config
from src.utils.db_handler import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


def _save_upload(org_id: int, src: UploadFile) -> Path:
    ext = Path(src.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext or 'unknown'}",
        )

    dest_dir = Path(Config.UPLOAD_DIR) / str(org_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4().hex}{ext}"

    with dest.open("wb") as fh:
        while chunk := src.file.read(1024 * 1024):
            fh.write(chunk)

    return dest


def persist_pending_upload(
    org_id: int,
    user_id: int,
    file_path: str,
    parsed: dict,
) -> int:
    """
    Insert a row into pending_uploads and return its id.
    Exposed at module level so the WhatsApp orchestrator can reuse it.
    """
    with get_db(org_id) as cur:
        cur.execute(
            """
            INSERT INTO pending_uploads
                (org_id, uploaded_by, file_path, parse_kind, parsed)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (org_id, user_id, file_path, parsed.get("kind", "unknown"),
             json.dumps(parsed, default=str)),
        )
        return cur.fetchone()["id"]


@router.post("/uploads")
async def api_upload_file(request: Request, file: UploadFile = File(...)):
    """
    Upload a faculty-supplied file. Returns:
        { upload_id, kind, summary, attendees }
    The caller drives the next step (confirm / discard / refine intent).
    """
    org_id  = getattr(request.state, "org_id", None)
    user_id = getattr(request.state, "user_id", None)
    if not org_id or not user_id:
        raise HTTPException(status_code=401, detail="Missing user context")

    saved_path = _save_upload(org_id, file)

    try:
        parsed = parse_file(str(saved_path))
    except ValueError as e:
        # Unsupported / unparseable — drop the file so we don't leak storage.
        try:
            os.remove(saved_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail=str(e)) from e

    attendees = extract_attendees(parsed)
    meeting   = extract_meeting_metadata(parsed)
    summary   = summarize(parsed, attendees)

    meeting_summary = summarize_meeting(meeting)
    if meeting_summary:
        summary = f"{summary}\n\nMeeting found in the file:\n{meeting_summary}"

    upload_id = persist_pending_upload(
        org_id, user_id, str(saved_path),
        {**parsed, "attendees": attendees, "meeting": meeting},
    )

    return {
        "success":         True,
        "upload_id":       upload_id,
        "kind":            parsed.get("kind"),
        "summary":         summary,
        "attendees":       attendees,
        "meeting":         meeting,
        "meeting_found":   bool(meeting and meeting.get("found")),
    }
