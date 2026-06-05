from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Tuple

from src.services.meeting_creator import create_meeting
from src.services.meeting_modifier import reschedule_meeting, cancel_meeting
from src.services.meeting_fetcher import search_meetings
from src.utils.rbac import require_roles

router = APIRouter()


class RecurrenceRule(BaseModel):
    frequency: str                        # DAILY | WEEKLY | MONTHLY
    interval: Optional[int] = 1
    count: Optional[int] = None           # number of occurrences
    days: Optional[List[str]] = None      # e.g. ["MO", "WE"] for WEEKLY


class CreateMeetingRequest(BaseModel):
    title: str
    start_datetime: str
    end_datetime: str
    participant_names: List[str]
    recurrence: Optional[RecurrenceRule] = None   # Feature 7


class RescheduleMeetingRequest(BaseModel):
    new_start_datetime: str
    new_end_datetime: str


class SearchMeetingsRequest(BaseModel):
    participants: Optional[List[str]] = None
    department: Optional[str] = None
    date_range: Optional[Tuple[str, str]] = None
    time_slot: Optional[Tuple[str, str]] = None


@router.post(
    "/meetings",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN", "SUPER_ADMIN"))],
)
async def api_create_meeting(body: CreateMeetingRequest, request: Request):
    """
    Create a new Google Calendar meeting.

    Includes:
      - Participant availability check (returns blocked_participants if busy)
      - Suggested alternative slots on conflict
      - Auto email + in-app notifications to all attendees
      - Optional recurrence rule (daily / weekly / monthly)
      - Celery 24h + 1h reminder tasks scheduled automatically
    """
    scheduler_email = getattr(request.state, "email", None)
    if not scheduler_email:
        raise HTTPException(
            status_code=400,
            detail="scheduler email not available — ensure email is included in JWT",
        )

    result = create_meeting(
        title=body.title,
        start_datetime=body.start_datetime,
        end_datetime=body.end_datetime,
        participant_names=body.participant_names,
        scheduler_email=scheduler_email,
        recurrence=body.recurrence.dict() if body.recurrence else None,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result)

    return result


@router.patch(
    "/meetings/{meeting_id}",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN", "SUPER_ADMIN"))],
)
async def api_reschedule_meeting(
    meeting_id: str, body: RescheduleMeetingRequest, request: Request
):
    """
    Reschedule an existing meeting to a new time slot.
    Returns suggested_alternatives if the new slot is also conflicted.
    """
    scheduler_email = getattr(request.state, "email", None)
    if not scheduler_email:
        raise HTTPException(status_code=400, detail="scheduler email not in JWT")

    result = reschedule_meeting(
        meeting_id=meeting_id,
        new_start_datetime=body.new_start_datetime,
        new_end_datetime=body.new_end_datetime,
        scheduler_email=scheduler_email,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result)

    return result


@router.delete(
    "/meetings/{meeting_id}",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN", "SUPER_ADMIN"))],
)
async def api_cancel_meeting(meeting_id: str, request: Request):
    """Cancel (delete) a meeting from Google Calendar and notify all participants."""
    scheduler_email = getattr(request.state, "email", None)
    if not scheduler_email:
        raise HTTPException(status_code=400, detail="scheduler email not in JWT")

    result = cancel_meeting(
        meeting_id=meeting_id,
        scheduler_email=scheduler_email,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@router.post(
    "/meetings/search",
    dependencies=[Depends(require_roles())],   # any authenticated user
)
async def api_search_meetings(body: SearchMeetingsRequest):
    """Search meetings in the local DB with optional filters."""
    filters = body.dict(exclude_none=True)
    result = search_meetings(filters)

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("message"))

    return result
