from fastapi import APIRouter, Request, HTTPException, Query
from typing import Optional

from src.services.smart_agenda_engine import generate_daily_briefing

router = APIRouter()


@router.get("/agenda")
async def api_daily_briefing(
    request: Request,
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    user_email: Optional[str] = Query(None, description="Override email; defaults to JWT user"),
):
    """
    Get a personalized daily meeting briefing for a faculty member.

    Returns meeting list, conflict alerts, and preparation suggestions.
    """
    email = user_email or getattr(request.state, "email", None)
    if not email:
        raise HTTPException(
            status_code=400,
            detail="user_email is required (or include email in JWT)"
        )

    result = generate_daily_briefing(user_email=email, date=date)

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("message"))

    return result
