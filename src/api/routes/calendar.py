from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from src.utils.self_healing_calendar import sync_calendar_changes
from src.utils.rbac import require_roles

router = APIRouter()


class CalendarSyncRequest(BaseModel):
    calendar_id: Optional[str] = "primary"
    lookback_minutes: Optional[int] = 120
    user_email: Optional[str] = None   # defaults to JWT user email


@router.post(
    "/calendar/sync",
    dependencies=[Depends(require_roles("FACULTY", "ADMIN", "SUPER_ADMIN"))],
)
async def api_sync_calendar(body: CalendarSyncRequest, request: Request):
    """
    Trigger a self-healing sync of Google Calendar events into the local DB.

    Detects created, updated, and deleted events in the last `lookback_minutes`
    and reconciles them with the local meetings table.
    """
    user_email = body.user_email or getattr(request.state, "email", None)
    if not user_email:
        raise HTTPException(
            status_code=400,
            detail="user_email is required (or include email in JWT)"
        )

    result = sync_calendar_changes(
        user_email=user_email,
        calendar_id=body.calendar_id,
        lookback_minutes=body.lookback_minutes,
    )

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("message"))

    return result
