"""
Room booking queue (BOOKING_AUTHORITY surface).

Routes:
    GET    /api/v1/bookings/pending             (list pending)
    POST   /api/v1/bookings/{id}/approve        (approve)
    POST   /api/v1/bookings/{id}/deny           (deny)
    POST   /api/v1/bookings/request             (any FACULTY/ADMIN — request)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.services.booking_service import (
    approve_booking,
    deny_booking,
    list_pending,
    request_booking,
)
from src.utils.rbac import require_roles

router = APIRouter()


class RequestPayload(BaseModel):
    room_label: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    purpose: Optional[str] = None
    meeting_id: Optional[str] = None


class DecisionPayload(BaseModel):
    notes: Optional[str] = None


def _serialize(b: dict) -> dict:
    out = {**b}
    for k in ("starts_at", "ends_at", "decided_at", "created_at"):
        if out.get(k) is not None and not isinstance(out[k], str):
            out[k] = out[k].isoformat()
    return out


@router.post(
    "/bookings/request",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN"))],
)
def create_request(payload: RequestPayload, request: Request):
    org_id = request.state.org_id
    user_id = request.state.user_id
    return request_booking(
        org_id=org_id, requested_by=user_id,
        room_label=payload.room_label,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        purpose=payload.purpose,
        meeting_id=payload.meeting_id,
    )


@router.get(
    "/bookings/pending",
    dependencies=[Depends(require_roles("BOOKING_AUTHORITY"))],
)
def get_pending(request: Request):
    org_id = request.state.org_id
    return {"success": True,
            "bookings": [_serialize(b) for b in list_pending(org_id)]}


@router.post(
    "/bookings/{booking_id}/approve",
    dependencies=[Depends(require_roles("BOOKING_AUTHORITY"))],
)
def approve(booking_id: int, payload: DecisionPayload, request: Request):
    user_id = request.state.user_id
    booking = approve_booking(booking_id, authority_id=user_id, notes=payload.notes)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return {"success": True, "booking": _serialize(booking)}


@router.post(
    "/bookings/{booking_id}/deny",
    dependencies=[Depends(require_roles("BOOKING_AUTHORITY"))],
)
def deny(booking_id: int, payload: DecisionPayload, request: Request):
    user_id = request.state.user_id
    booking = deny_booking(booking_id, authority_id=user_id, notes=payload.notes)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return {"success": True, "booking": _serialize(booking)}
