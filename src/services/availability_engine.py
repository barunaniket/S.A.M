from datetime import datetime, timedelta
from typing import Optional
from src.utils.google_auth import get_calendar_service


def calculate_free_slots(
    range_start: str,
    range_end: str,
    duration_minutes: int = 60,
    buffer_minutes: int = 15,
    busy_payload: Optional[dict] = None,
    user_email: Optional[str] = None
) -> dict:
    """
    Calculates free time slots by subtracting busy intervals from working hours.

    Supports:
    - Production Mode (Google FreeBusy API)
    - Testing Mode (Injected busy JSON payload)

    Phase 3 Compatible
    """

    try:

        # 🔵 1️⃣ Decide Source of Busy Data
        if busy_payload:
            busy_periods = busy_payload.get("busy", [])

        else:
            service = get_calendar_service()

            body = {
                "timeMin": range_start,
                "timeMax": range_end,
                "items": [{"id": user_email}]
            }

            freebusy_result = service.freebusy().query(body=body).execute()
            busy_periods = freebusy_result["calendars"][user_email]["busy"]

        # 🔵 2️⃣ Convert Working Hours
        working_start = datetime.fromisoformat(range_start.replace("Z", ""))
        working_end = datetime.fromisoformat(range_end.replace("Z", ""))

        busy_intervals = []

        # 🔵 3️⃣ Apply Buffer Geometry
        for period in busy_periods:
            start = datetime.fromisoformat(period["start"].replace("Z", ""))
            end = datetime.fromisoformat(period["end"].replace("Z", ""))

            start -= timedelta(minutes=buffer_minutes)
            end += timedelta(minutes=buffer_minutes)

            busy_intervals.append((start, end))

        # 🔵 4️⃣ Sort Busy Intervals
        busy_intervals.sort(key=lambda x: x[0])

        free_slots = []
        pointer = working_start

        # 🔵 5️⃣ Bipartite Subtraction Algorithm
        for busy_start, busy_end in busy_intervals:

            if pointer < busy_start:
                gap = busy_start - pointer

                if gap >= timedelta(minutes=duration_minutes):
                    free_slots.append({
                        "start": pointer.isoformat(),
                        "end": busy_start.isoformat()
                    })

            pointer = max(pointer, busy_end)

        # 🔵 6️⃣ Final Gap
        if pointer < working_end:
            gap = working_end - pointer

            if gap >= timedelta(minutes=duration_minutes):
                free_slots.append({
                    "start": pointer.isoformat(),
                    "end": working_end.isoformat()
                })

        # 🔵 7️⃣ Worker Protocol Return
        return {
            "success": True,
            "data": {
                "free_slots": free_slots,
                "total_slots": len(free_slots)
            },
            "message": "Free slots calculated",
            "error_code": None
        }

    except Exception as e:
        return {
            "success": False,
            "data": None,
            "message": str(e),
            "error_code": "AVAILABILITY_ENGINE_ERROR"
        }
