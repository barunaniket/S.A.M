"""
This file basically check krega ki user kee google calender
me ek defined time slot me koi dusra event clash toh nahi
kar rha hai na
"""

import datetime
from .google_auth import get_calendar_service

def check_scheduler_conflict(scheduler_email: str, start_datetime: str, end_datetime: str) -> bool:
    """
    Checks the scheduler's Google Calendar for any existing events during the requested time slot.

    Args:
        scheduler_email (str): The email of the user to check (used for context/logging).
        start_datetime (str): ISO 8601 start time (e.g., "2025-01-27T15:00:00").
        end_datetime (str): ISO 8601 end time (e.g., "2025-01-27T16:00:00").

    Returns:
        bool: True if a conflict exists (BUSY), False if the slot is free.
    """
    try:
        service = get_calendar_service()

        time_min = start_datetime if 'Z' in start_datetime or '+' in start_datetime else f"{start_datetime}Z"
        time_max = end_datetime if 'Z' in end_datetime or '+' in end_datetime else f"{end_datetime}Z"

        events_result = service.events().list(
            calendarId='primary', 
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])

        if not events:
            return False
        
        
        return True

    except Exception as e:
        print(f"Error checking conflicts for {scheduler_email}: {str(e)}")
        return True
    
"""
isko use kaise karna hai?

from utils.conflict_detector import check_scheduler_conflict

if check_scheduler_conflict(scheduler_email, start_time, end_time):
    return {"success": False, "error": "Conflict detected"}
"""