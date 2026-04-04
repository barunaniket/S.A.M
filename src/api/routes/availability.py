from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from src.services.availability_engine import calculate_free_slots

router = APIRouter()


class WorkingHours(BaseModel):
    start: str = "09:00"              # HH:MM
    end: str = "17:00"                # HH:MM
    days: Optional[List[int]] = [0, 1, 2, 3, 4]  # 0=Mon … 6=Sun


class AvailabilityRequest(BaseModel):
    range_start: str
    range_end: str
    duration_minutes: Optional[int] = 60
    buffer_minutes: Optional[int] = 15
    user_email: Optional[str] = None       # override; defaults to JWT user
    busy_payload: Optional[dict] = None    # for testing without hitting Google API
    working_hours: Optional[WorkingHours] = None  # Feature 5


@router.post("/availability")
async def api_get_availability(body: AvailabilityRequest, request: Request):
    """
    Calculate free time slots within a working window for a user.

    Feature 5: Pass working_hours to restrict results to business hours
    (e.g. {"start": "09:00", "end": "17:00", "days": [0, 1, 2, 3, 4]}).

    Pass busy_payload to bypass the Google API (useful for frontend testing).
    """
    user_email = body.user_email or getattr(request.state, "email", None)
    if not user_email and not body.busy_payload:
        raise HTTPException(
            status_code=400,
            detail="user_email is required (or include email in JWT)",
        )

    result = calculate_free_slots(
        range_start=body.range_start,
        range_end=body.range_end,
        user_email=user_email or "",
        duration_minutes=body.duration_minutes,
        buffer_minutes=body.buffer_minutes,
        busy_payload=body.busy_payload,
        working_hours=body.working_hours.dict() if body.working_hours else None,
    )

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("message"))

    return result
