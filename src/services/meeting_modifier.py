"""
meeting_modifier.py
-------------------
Reschedule and cancel Google Calendar events.

Features added:
  Feature 2 — Auto email + in-app notifications to participants on update/cancel
  Feature 4 — Suggest alternative slots when a conflict is detected on reschedule
  Feature 9 — Keep local DB in sync after every change
"""

from datetime import datetime, timedelta

from googleapiclient.errors import HttpError

from src.utils.google_auth import get_calendar_service
from src.utils.conflict_detector import check_scheduler_conflict
from src.utils.date_parser import parse_iso_from_llm
from src.utils.db_handler import get_db_connection, release_db_connection, get_user_by_email
from src.services.availability_engine import find_common_slots
from src.services.email_queue import queue_email
from src.services.notification import create_notification


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_alternative_slots(
    organizer_email: str,
    participant_emails: list,
    start_datetime: str,
    end_datetime: str,
) -> list:
    """Return up to 3 common free slots in a ±2-day window around the conflicted time."""
    try:
        start    = datetime.fromisoformat(start_datetime.replace("Z", ""))
        end      = datetime.fromisoformat(end_datetime.replace("Z", ""))
        duration = int((end - start).total_seconds() / 60)

        result = find_common_slots(
            organizer_email=organizer_email,
            participant_emails=participant_emails,
            window_start=(start - timedelta(days=2)).isoformat(),
            window_end=(start + timedelta(days=2)).isoformat(),
            duration_minutes=duration,
        )
        if result.get("success") and result.get("data"):
            return result["data"].get("free_slots", [])
    except Exception:
        pass
    return []


def _notify_participants(
    participant_emails: list,
    notification_type: str,
    meeting_details: dict,
):
    """Queue email + in-app notification for every participant."""
    subject_map = {
        "update": f"Meeting Updated: {meeting_details.get('title')}",
        "cancel": f"Meeting Cancelled: {meeting_details.get('title')}",
    }
    subject = subject_map.get(notification_type, f"Meeting: {meeting_details.get('title')}")
    body = (
        f"{notification_type.capitalize()}: {meeting_details.get('title')}\n"
        f"Start    : {meeting_details.get('start', 'N/A')}\n"
        f"End      : {meeting_details.get('end', 'N/A')}\n"
        f"Organizer: {meeting_details.get('organizer', 'N/A')}"
    )

    for email in participant_emails:
        try:
            queue_email(to_addr=email, subject=subject, body=body)
        except Exception as e:
            print(f"[meeting_modifier] Email queue failed for {email}: {e}")

        try:
            user = get_user_by_email(email)
            if user:
                create_notification(
                    user_id=user["id"],
                    message=f"{notification_type.capitalize()}: \"{meeting_details.get('title')}\" at {meeting_details.get('start', 'N/A')}",
                    notification_type=notification_type,
                )
        except Exception as e:
            print(f"[meeting_modifier] In-app notification failed for {email}: {e}")


def _update_db_meeting(meeting_id: str, new_start: str, new_end: str):
    """Update start/end time for the given Google event ID in local DB. Non-fatal."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE meetings
            SET start_time = %s, end_time = %s
            WHERE meeting_id = %s;
            """,
            (new_start, new_end, meeting_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"[meeting_modifier] DB update failed (non-fatal): {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            release_db_connection(conn)


def _delete_db_meeting(meeting_id: str):
    """Remove the meeting from local DB by Google event ID. Non-fatal."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Delete participants first (FK), then the meeting row
        cur.execute(
            """
            DELETE FROM meeting_participants
            WHERE meeting_id IN (
                SELECT id FROM meetings WHERE meeting_id = %s
            );
            """,
            (meeting_id,),
        )
        cur.execute("DELETE FROM meetings WHERE meeting_id = %s;", (meeting_id,))
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"[meeting_modifier] DB delete failed (non-fatal): {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            release_db_connection(conn)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reschedule_meeting(
    meeting_id: str,
    new_start_datetime: str,
    new_end_datetime: str,
    scheduler_email: str,
) -> dict:
    """
    Reschedule an existing Google Calendar event to a new time slot.

    On conflict the response includes:
        "suggested_alternatives": [{start, end}, ...]   (up to 3 slots)
    """

    try:
        new_start = parse_iso_from_llm(new_start_datetime)
        new_end   = parse_iso_from_llm(new_end_datetime)

        if not new_start or not new_end:
            return {"success": False, "error": "Invalid datetime format provided"}

        service = get_calendar_service(user_email=scheduler_email)

        event = service.events().get(calendarId="primary", eventId=meeting_id).execute()

        # Gather existing participant emails for notifications + suggestions
        participant_emails = [
            a["email"] for a in event.get("attendees", []) if a.get("email")
        ]

        conflict = check_scheduler_conflict(scheduler_email, new_start_datetime, new_end_datetime)
        if conflict:
            alternatives = _get_alternative_slots(
                scheduler_email, participant_emails,
                new_start_datetime, new_end_datetime,
            )
            return {
                "success": False,
                "error": "New time conflicts with an existing meeting",
                "suggested_alternatives": alternatives,
            }

        event["start"] = {"dateTime": new_start.isoformat(), "timeZone": "UTC"}
        event["end"]   = {"dateTime": new_end.isoformat(),   "timeZone": "UTC"}

        updated_event = service.events().patch(
            calendarId="primary",
            eventId=meeting_id,
            body=event,
        ).execute()

        new_start_iso = updated_event["start"]["dateTime"]
        new_end_iso   = updated_event["end"]["dateTime"]
        title         = updated_event.get("summary", "")

        # Feature 9: Update local DB
        _update_db_meeting(meeting_id, new_start_iso, new_end_iso)

        # Feature 2: Notify participants
        _notify_participants(
            participant_emails, "update",
            {
                "title":     title,
                "start":     new_start_iso,
                "end":       new_end_iso,
                "organizer": scheduler_email,
            },
        )

        return {
            "success":       True,
            "meeting_id":    updated_event["id"],
            "updated_start": new_start_iso,
            "updated_end":   new_end_iso,
            "message":       "Meeting rescheduled successfully",
        }

    except HttpError as error:
        if error.resp.status == 404:
            return {"success": False, "error": "Meeting not found"}
        return {"success": False, "error": f"Google API error: {error}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def cancel_meeting(meeting_id: str, scheduler_email: str) -> dict:
    """Delete a Google Calendar event and clean up local DB + notify participants."""

    try:
        service = get_calendar_service(user_email=scheduler_email)

        event = service.events().get(calendarId="primary", eventId=meeting_id).execute()
        title = event.get("summary", "")
        participant_emails = [
            a["email"] for a in event.get("attendees", []) if a.get("email")
        ]

        service.events().delete(calendarId="primary", eventId=meeting_id).execute()

        # Feature 9: Remove from local DB
        _delete_db_meeting(meeting_id)

        # Feature 2: Notify participants
        _notify_participants(
            participant_emails, "cancel",
            {"title": title, "organizer": scheduler_email},
        )

        return {
            "success":    True,
            "meeting_id": meeting_id,
            "message":    "Meeting cancelled successfully",
        }

    except HttpError as error:
        if error.resp.status == 404:
            return {"success": False, "error": "Meeting not found or already deleted"}
        return {"success": False, "error": f"Google API error: {error}"}

    except Exception as e:
        return {"success": False, "error": str(e)}
