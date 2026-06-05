"""
Course material library + MCQ generation routes.

    GET  /api/v1/materials                       list (filter by subject)
    POST /api/v1/materials                       multipart upload
    POST /api/v1/materials/{id}/generate-mcqs    LLM-draft N candidates
    GET  /api/v1/materials/bank?subject=...      bank rows (approved + pending)
    POST /api/v1/materials/bank/approve          approve bank ids

Faculty / admin / super-admin RBAC.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException,
    Query, Request, UploadFile,
)
from pydantic import BaseModel

from src.services import course_materials, file_ingestor, mcq_generator
from src.utils.rbac import require_roles

router = APIRouter()


_UPLOAD_DIR = Path(os.environ.get("SAM_MATERIALS_DIR", "data/materials"))
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _save_upload(file: UploadFile) -> Path:
    safe_name = (file.filename or "upload").replace("/", "_")
    suffix = Path(safe_name).suffix.lower()
    target = _UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    with target.open("wb") as fh:
        while True:
            chunk = file.file.read(1024 * 64)
            if not chunk:
                break
            fh.write(chunk)
    return target


@router.get(
    "/materials",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN", "SUPER_ADMIN"))],
)
def list_all(request: Request, subject: Optional[str] = None):
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    rows = course_materials.list_materials(int(org_id), subject=subject)
    for r in rows:
        v = r.get("created_at")
        if v is not None and hasattr(v, "isoformat"):
            r["created_at"] = v.isoformat()
    return {"success": True, "data": rows}


@router.post(
    "/materials",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN", "SUPER_ADMIN"))],
)
async def upload(
    request: Request,
    subject: str = Form(...),
    title: Optional[str] = Form(None),
    batch: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    org_id = getattr(request.state, "org_id", None)
    user_id = getattr(request.state, "user_id", None)
    if not org_id or not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    target = _save_upload(file)
    try:
        parsed = file_ingestor.parse_file(str(target))
    except Exception as e:
        try:
            target.unlink()
        except Exception:
            pass
        raise HTTPException(status_code=422,
                            detail=f"Couldn't parse the file: {e}")

    extracted = (parsed.get("text") or "").strip() or None

    row = course_materials.record_material(
        org_id=int(org_id),
        subject=subject,
        batch=batch,
        title=title or file.filename or "Material",
        file_path=str(target),
        mime_type=parsed.get("kind"),
        extracted_text=extracted,
        uploaded_by=int(user_id),
    )
    v = row.get("created_at")
    if v is not None and hasattr(v, "isoformat"):
        row["created_at"] = v.isoformat()
    return {"success": True, "data": row}


class GeneratePayload(BaseModel):
    count: int = 5


@router.post(
    "/materials/{material_id}/generate-mcqs",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN", "SUPER_ADMIN"))],
)
def generate(material_id: int, payload: GeneratePayload, request: Request):
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    material = course_materials.get_material(material_id)
    if not material or material["org_id"] != org_id:
        raise HTTPException(status_code=404, detail="Material not found.")

    result = mcq_generator.generate_from_text(
        subject=material["subject"],
        text=material.get("extracted_text") or "",
        count=int(payload.count or 5),
    )
    if not result.get("success"):
        raise HTTPException(status_code=400,
                            detail=result.get("message") or "Generation failed.")

    bank_ids = course_materials.bulk_insert_questions(
        org_id=int(org_id),
        subject=material["subject"],
        source_material_id=material_id,
        questions=result["questions"],
    )
    return {"success": True,
            "data": {"bank_ids": bank_ids,
                     "questions": result["questions"]}}


@router.get(
    "/materials/bank",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN", "SUPER_ADMIN"))],
)
def list_bank_rows(request: Request,
                   subject: str = Query(..., min_length=1),
                   approved_only: bool = False):
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    rows = course_materials.list_bank(int(org_id), subject,
                                       approved_only=approved_only)
    for r in rows:
        for k in ("approved_at", "created_at"):
            v = r.get(k)
            if v is not None and hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    return {"success": True, "data": rows}


class ApprovePayload(BaseModel):
    ids: List[int]


@router.post(
    "/materials/bank/approve",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN", "SUPER_ADMIN"))],
)
def approve_bank(payload: ApprovePayload, request: Request):
    org_id = getattr(request.state, "org_id", None)
    user_id = getattr(request.state, "user_id", None)
    if not org_id or not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    n = course_materials.approve(
        org_id=int(org_id), ids=payload.ids, approved_by=int(user_id),
    )
    return {"success": True, "data": {"approved": n}}
