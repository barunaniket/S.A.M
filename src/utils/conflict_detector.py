"""
conflict_detector.py
--------------------
Check a user's Google Calendar for conflicting events in a given time slot.
"""

from src.utils.google_auth import get_calendar_service


def check_scheduler_conflict(
    scheduler_email: str,
    start_datetime: str,
    end_datetime: str,
) -> bool:
    """
    Return True if the scheduler has a blocking event in the requested slot.

    Parameters
    ----------
    scheduler_email : str  — email used to fetch stored OAuth credentials
    start_datetime  : str  — ISO 8601 start (e.g. "2026-04-04T15:00:00")
    end_datetime    : str  — ISO 8601 end   (e.g. "2026-04-04T16:00:00")
    """
    try:
        service = get_calendar_service(user_email=scheduler_email)

        # Ensure timestamps have a timezone indicator for the Google API
        def _ensure_tz(dt: str) -> str:
            if dt and not any(c in dt for c in ("Z", "+", "-", "T")):
                return dt + "Z"
            if "T" in dt and "Z" not in dt and "+" not in dt and dt.count("-") == 2:
                return dt + "Z"
            return dt

        time_min = _ensure_tz(start_datetime)
        time_max = _ensure_tz(end_datetime)

        events_result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = events_result.get("items", [])

        for event in events:
            # "transparent" events are show-as-free and should not block
            if event.get("transparency") == "transparent":
                continue
            return True   # found at least one blocking event

        return False

    except Exception as e:
        # Fail-safe: treat errors as conflicts to avoid double-booking
        print(f"[conflict_detector] Error checking conflicts for {scheduler_email}: {e}")
        return True
