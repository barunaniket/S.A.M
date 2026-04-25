"""
REST surface for faculty-defined user groups.

    GET    /api/v1/groups                       list groups in your org
    POST   /api/v1/groups                       create
    DELETE /api/v1/groups/{group_id}            delete
    GET    /api/v1/groups/{group_id}/members    list members
    POST   /api/v1/groups/{group_id}/members    add members (by id OR by email)
    DELETE /api/v1/groups/{group_id}/members/{user_id}
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel

from src.services import group_service

router = APIRouter()


def _ctx(request: Request):
    org_id  = getattr(request.state, "org_id", None)
    user_id = getattr(request.state, "user_id", None)
    if not org_id:
        raise HTTPException(status_code=401, detail="Missing org context")
    return org_id, user_id


class CreateGroupRequest(BaseModel):
    name: str
    description: Optional[str] = None


class AddMembersRequest(BaseModel):
    user_ids: Optional[List[int]] = None
    emails:   Optional[List[str]] = None


@router.get("/groups")
async def api_list_groups(request: Request):
    org_id, _ = _ctx(request)
    return {"success": True, "data": group_service.list_groups(org_id)}


@router.post("/groups")
async def api_create_group(body: CreateGroupRequest, request: Request):
    org_id, user_id = _ctx(request)
    result = group_service.create_group(
        org_id=org_id,
        name=body.name,
        description=body.description,
        created_by=user_id,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.delete("/groups/{group_id}")
async def api_delete_group(group_id: int, request: Request):
    org_id, _ = _ctx(request)
    result = group_service.delete_group(org_id, group_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.get("/groups/{group_id}/members")
async def api_list_members(group_id: int, request: Request):
    org_id, _ = _ctx(request)
    return {"success": True, "data": group_service.list_members(org_id, group_id)}


@router.post("/groups/{group_id}/members")
async def api_add_members(group_id: int, body: AddMembersRequest, request: Request):
    org_id, _ = _ctx(request)

    if not body.user_ids and not body.emails:
        raise HTTPException(status_code=400,
                            detail="Provide user_ids or emails.")

    added = 0
    missing: list = []
    if body.user_ids:
        for uid in body.user_ids:
            r = group_service.add_member(org_id, group_id, uid)
            if r.get("success"):
                added += 1
    if body.emails:
        r = group_service.add_members_by_email(org_id, group_id, body.emails)
        if not r.get("success"):
            raise HTTPException(status_code=400, detail=r.get("error"))
        added += r.get("matched", 0)
        missing.extend(r.get("missing", []))

    return {"success": True, "added": added, "missing_emails": missing}


@router.delete("/groups/{group_id}/members/{user_id}")
async def api_remove_member(group_id: int, user_id: int, request: Request):
    org_id, _ = _ctx(request)
    result = group_service.remove_member(org_id, group_id, user_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result
