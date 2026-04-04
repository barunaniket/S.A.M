"""
availability_engine.py
----------------------
Calculates free time slots for one or more calendars.

New features:
  - Working hours enforcement (filter slots outside 9-5 / custom window)
  - find_common_slots(): intersect free time across all participants
"""

from datetime import datetime, timedelta
from typing import Optional, List

from src.utils.google_auth import get_calendar_service


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _filter_by_working_hours(slots: list, working_hours: dict) -> list:
    """
    Clip free slots to a working-hours window on allowed weekdays.

    working_hours format:
        {
            "start": "09:00",          # HH:MM
            "end":   "17:00",          # HH:MM
            "days":  [0, 1, 2, 3, 4]   # 0=Mon … 6=Sun (default Mon-Fri)
        }
    """
    if not working_hours:
        return slots

    start_h, start_m = map(int, working_hours.get("start", "09:00").split(":"))
    end_h,   end_m   = map(int, working_hours.get("end",   "17:00").split(":"))
    allowed_days = set(working_hours.get("days", [0, 1, 2, 3, 4]))

    filtered = []
    for slot in slots:
        slot_start = datetime.fromisoformat(slot["start"])
        slot_end   = datetime.fromisoformat(slot["end"])

        if slot_start.weekday() not in allowed_days:
            continue

        wh_start = slot_start.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        wh_end   = slot_start.replace(hour=end_h,   minute=end_m,   second=0, microsecond=0)

        clipped_start = max(slot_start, wh_start)
        clipped_end   = min(slot_end,   wh_end)

        if clipped_end > clipped_start:
            filtered.append({
                "start": clipped_start.isoformat(),
                "end":   clipped_end.isoformat(),
            })

    return filtered


# ---------------------------------------------------------------------------
# Public: single-user free slots
# ---------------------------------------------------------------------------

def calculate_free_slots(
    range_start: str,
    range_end: str,
    user_email: str,
    duration_minutes: int = 60,
    buffer_minutes: int = 15,
    busy_payload: Optional[dict] = None,
    working_hours: Optional[dict] = None,
) -> dict:
    """
    Calculate free time slots by subtracting busy intervals from the window.

    Parameters
    ----------
    range_start      : ISO 8601 start of the working window
    range_end        : ISO 8601 end of the working window
    user_email       : email used to look up Google OAuth credentials
    duration_minutes : minimum slot length to include (default 60)
    buffer_minutes   : padding added around each busy period (default 15)
    busy_payload     : optional override {"busy": [{"start":..., "end":...}]}
    working_hours    : optional filter {"start": "09:00", "end": "17:00", "days": [0..4]}
    """

    try:
        if busy_payload:
            busy_periods = busy_payload.get("busy", [])
        else:
            service = get_calendar_service(user_email=user_email)
            body = {
                "timeMin": range_start,
                "timeMax": range_end,
                "items": [{"id": user_email}],
            }
            freebusy_result = service.freebusy().query(body=body).execute()
            busy_periods = freebusy_result["calendars"][user_email]["busy"]

        working_start = datetime.fromisoformat(range_start.replace("Z", ""))
        working_end   = datetime.fromisoformat(range_end.replace("Z", ""))

        busy_intervals = []
        for period in busy_periods:
            start = datetime.fromisoformat(period["start"].replace("Z", ""))
            end   = datetime.fromisoformat(period["end"].replace("Z", ""))
            start -= timedelta(minutes=buffer_minutes)
            end   += timedelta(minutes=buffer_minutes)
            busy_intervals.append((start, end))

        busy_intervals.sort(key=lambda x: x[0])

        free_slots = []
        pointer = working_start

        for busy_start, busy_end in busy_intervals:
            if pointer < busy_start:
                if busy_start - pointer >= timedelta(minutes=duration_minutes):
                    free_slots.append({
                        "start": pointer.isoformat(),
                        "end":   busy_start.isoformat(),
                    })
            pointer = max(pointer, busy_end)

        if pointer < working_end:
            if working_end - pointer >= timedelta(minutes=duration_minutes):
                free_slots.append({
                    "start": pointer.isoformat(),
                    "end":   working_end.isoformat(),
                })

        if working_hours:
            free_slots = _filter_by_working_hours(free_slots, working_hours)

        return {
            "success": True,
            "data": {
                "free_slots":   free_slots,
                "total_slots":  len(free_slots),
            },
            "message": "Free slots calculated",
            "error_code": None,
        }

    except Exception as e:
        return {
            "success":    False,
            "data":       None,
            "message":    str(e),
            "error_code": "AVAILABILITY_ENGINE_ERROR",
        }


# ---------------------------------------------------------------------------
# Public: common free slots across multiple participants (Feature 4 support)
# ---------------------------------------------------------------------------

def find_common_slots(
    organizer_email: str,
    participant_emails: List[str],
    window_start: str,
    window_end: str,
    duration_minutes: int = 60,
    buffer_minutes: int = 15,
) -> dict:
    """
    Find time slots that are free for the organizer AND all participants.

    Uses the organizer's credentials to call the Google FreeBusy API for all
    calendars in a single request, then computes the intersection.
    Returns at most 3 suggestions.

    Parameters
    ----------
    organizer_email     : email used for OAuth + FreeBusy query
    participant_emails  : list of participant emails to include in the check
    window_start        : ISO 8601 start of the search window
    window_end          : ISO 8601 end of the search window
    duration_minutes    : minimum slot length to include
    buffer_minutes      : padding around busy periods
    """

    try:
        service = get_calendar_service(user_email=organizer_email)

        all_emails = list(set([organizer_email] + participant_emails))
        body = {
            "timeMin": window_start,
            "timeMax": window_end,
            "items":   [{"id": e} for e in all_emails],
        }
        freebusy = service.freebusy().query(body=body).execute()

        combined_busy = []
        for email in all_emails:
            for period in freebusy.get("calendars", {}).get(email, {}).get("busy", []):
                combined_busy.append(period)

        result = calculate_free_slots(
            range_start=window_start,
            range_end=window_end,
            user_email=organizer_email,
            duration_minutes=duration_minutes,
            buffer_minutes=buffer_minutes,
            busy_payload={"busy": combined_busy},
        )

        if result["success"] and result["data"]:
            slots = result["data"]["free_slots"][:3]
            result["data"]["free_slots"]  = slots
            result["data"]["total_slots"] = len(slots)

        return result

    except Exception as e:
        return {
            "success":    False,
            "data":       None,
            "message":    str(e),
            "error_code": "COMMON_SLOTS_ERROR",
        }
