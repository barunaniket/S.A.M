"""
analytics.py
------------
Feature 10: Meeting analytics endpoint.

GET /api/v1/analytics/meetings
  ?from_date=2026-01-01
  &to_date=2026-04-04
  &user_email=optional@override.com   (defaults to JWT email)
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from typing import Optional

from src.services.meeting_analytics import get_meeting_analytics
from src.utils.rbac import require_roles

router = APIRouter()


@router.get(
    "/analytics/meetings",
    dependencies=[Depends(require_roles("ADMIN", "SUPER_ADMIN"))],
)
async def api_meeting_analytics(
    from_date: str,
    to_date: str,
    user_email: Optional[str] = None,
    request: Request = None,
):
    """
    Return aggregated meeting statistics for a user over a date range.

    Response includes:
      - total_meetings
      - avg_duration_minutes
      - busiest_day_of_week
      - top_participants (top 5 by frequency)
      - conflicting_meetings (count)
      - conflict_rate_pct
    """
    email = user_email or getattr(request.state, "email", None)
    if not email:
        raise HTTPException(
            status_code=400,
            detail="user_email is required (or include email in JWT)",
        )

    result = get_meeting_analytics(email, from_date, to_date)

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("message"))

    return result
