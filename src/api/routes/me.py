from fastapi import APIRouter, Request
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError

from src.utils.db_handler import get_user_by_email
from src.utils.google_auth import get_calendar_service

router = APIRouter()


@router.get("/me/google-status")
async def google_status(request: Request):
    """
    Reports whether the SPOC's stored Google credentials still work.

    The frontend's OAuth status pill polls this. Three outcomes:
      • connected: true                       — token works, calendar reachable
      • connected: false, reason: no_token    — user row has no refresh token
      • connected: false, reason: expired     — refresh failed (revoked / expired)
    """
    email = getattr(request.state, "email", None)
    if not email:
        return {
            "success": False,
            "data": None,
            "message": "JWT is missing the email claim",
            "error_code": "MISSING_EMAIL",
        }

    user = get_user_by_email(email)
    if not user or not user.get("encrypted_refresh_token"):
        return {
            "success": True,
            "data": {"connected": False, "reason": "no_token", "email": email},
            "message": "No Google refresh token on file",
            "error_code": None,
        }

    try:
        service = get_calendar_service(user_email=email)
        # Cheapest authenticated call that exercises the refresh path AND
        # works with the calendar.events scope we actually request.
        service.events().list(calendarId="primary", maxResults=1).execute()
    except (RefreshError, HttpError, ValueError) as exc:
        return {
            "success": True,
            "data": {"connected": False, "reason": "expired", "email": email},
            "message": f"Google credentials no longer valid: {exc}",
            "error_code": None,
        }

    return {
        "success": True,
        "data": {"connected": True, "email": email},
        "message": "Google connection healthy",
        "error_code": None,
    }
