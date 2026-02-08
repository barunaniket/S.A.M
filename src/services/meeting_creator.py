"""
meeting_creator.py
Owner: Bismun

Responsibility:
Create a new meeting using Google Calendar API
"""

# --- Required dependencies (DO NOT CHANGE) ---
from utils.user_resolver import resolve_participants
from utils.conflict_detector import check_scheduler_conflict
from utils.google_auth import get_calendar_service


def create_meeting(
    title: str,
    start_datetime: str,
    end_datetime: str,
    participant_names: list,
    scheduler_email: str
) -> dict:
    """
    Creates a new Google Calendar event.

    Parameters:
    title (str): Meeting title
    start_datetime (str): ISO 8601 start datetime
    end_datetime (str): ISO 8601 end datetime
    participant_names (list): List of participant names
    scheduler_email (str): Email of meeting organizer

    Returns:
    dict: Success or failure response
    """

    try:
        # 1️⃣ Resolve participant names to email addresses
        participants = resolve_participants(participant_names)

        # 2️⃣ Check scheduler availability
        conflict = check_scheduler_conflict(
            scheduler_email,
            start_datetime,
            end_datetime
        )

        # 3️⃣ If conflict exists → return failure
        if conflict:
            return {
                "success": False,
                "error": "Conflict detected: Scheduler is busy",
                "conflicting_events": conflict
            }

        # 4️⃣ Get authenticated Google Calendar service
        service = get_calendar_service(scheduler_email)

        # 5️⃣ Prepare Google Calendar event body
        event_body = {
            "summary": title,
            "start": {
                "dateTime": start_datetime
            },
            "end": {
                "dateTime": end_datetime
            },
            "attendees": [
                {"email": email} for email in participants
            ]
        }

        # 6️⃣ Insert event into Google Calendar
        event = service.events().insert(
            calendarId="primary",
            body=event_body
        ).execute()

        # 7️⃣ Return success response
        return {
            "success": True,
            "meeting_id": event.get("id"),
            "event_link": event.get("htmlLink"),
            "participants": participants,
            "start": start_datetime,
            "end": end_datetime
        }

    except Exception as e:
        # 8️⃣ Handle unexpected failures
        return {
            "success": False,
            "error": str(e)
        }
