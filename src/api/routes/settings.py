"""
Per-org feature toggles (org_settings table). Super-admin only.

    GET   /api/v1/settings           full snapshot (defaults applied)
    PATCH /api/v1/settings           update one or more keys
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.services import org_settings
from src.utils.rbac import require_roles

router = APIRouter()


@router.get(
    "/settings",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def get_all(request: Request):
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return {"success": True, "data": org_settings.all_for_org(int(org_id))}


class SettingsPatch(BaseModel):
    settings: Dict[str, Any]


@router.patch(
    "/settings",
    dependencies=[Depends(require_roles("SUPER_ADMIN"))],
)
def patch(payload: SettingsPatch, request: Request):
    org_id = getattr(request.state, "org_id", None)
    user_id = getattr(request.state, "user_id", None)
    if not org_id or not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    for k, v in (payload.settings or {}).items():
        org_settings.set(int(org_id), k, v, updated_by=int(user_id))

    return {"success": True,
            "data": org_settings.all_for_org(int(org_id))}
