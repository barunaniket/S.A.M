from googleapiclient.errors import HttpError
from utils.google_auth import get_calendar_service
from utils.conflict_detector import check_scheduler_conflict
from utils.date_parser import parse_iso_datetime


def reschedule_meeting(meeting_id: str,
                       new_start_datetime: str,
                       new_end_datetime: str,
                       scheduler_email: str) -> dict:
    """
    Reschedules an existing meeting to a new time.
    """

    try:
        
        new_start = parse_iso_datetime(new_start_datetime)
        new_end = parse_iso_datetime(new_end_datetime)

        
        service = get_calendar_service()

       
        event = service.events().get(
            calendarId='primary',
            eventId=meeting_id
        ).execute()

       
        conflict = check_scheduler_conflict(
            scheduler_email,
            new_start,
            new_end
        )

        if conflict:
            return {
                "success": False,
                "error": "New time conflicts with an existing meeting"
            }

       
        event['start'] = {
            'dateTime': new_start,
            'timeZone': 'UTC'
        }
        event['end'] = {
            'dateTime': new_end,
            'timeZone': 'UTC'
        }

        
        updated_event = service.events().patch(
            calendarId='primary',
            eventId=meeting_id,
            body=event
        ).execute()

        return {
            "success": True,
            "meeting_id": updated_event["id"],
            "updated_start": updated_event["start"]["dateTime"],
            "updated_end": updated_event["end"]["dateTime"],
            "message": "Meeting rescheduled successfully"
        }

    except HttpError as error:
        if error.resp.status == 404:
            return {"success": False, "error": "Meeting not found"}
        return {"success": False, "error": f"Google API error: {error}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def cancel_meeting(meeting_id: str, scheduler_email: str) -> dict:
    """
    
    """

    try:
        
        service = get_calendar_service()

       
        service.events().get(
            calendarId='primary',
            eventId=meeting_id
        ).execute()

        
        service.events().delete(
            calendarId='primary',
            eventId=meeting_id
        ).execute()

        return {
            "success": True,
            "meeting_id": meeting_id,
            "message": "Meeting cancelled successfully"
        }

    except HttpError as error:
        if error.resp.status == 404:
            return {"success": False, "error": "Meeting not found or already deleted"}
        return {"success": False, "error": f"Google API error: {error}"}

    except Exception as e:
        return {"success": False, "error": str(e)}
