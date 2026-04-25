"""
meeting_creator.py
------------------
Creates a new Google Calendar meeting event.

Features added:
  Feature 2  — Auto email + in-app notifications to all participants after creation
  Feature 3  — Participant availability check before scheduling
  Feature 4  — Suggest alternative slots when a conflict is found
  Feature 6  — Schedule Celery 24h / 1h reminder tasks
  Feature 7  — Recurring meeting support via Google Calendar RRULE
  Feature 9  — Persist meeting to local PostgreSQL DB after creation
"""

from datetime import datetime, timedelta
from typing import Optional

from src.utils.user_resolver import resolve_participants
from src.utils.conflict_detector import check_scheduler_conflict
from src.utils.google_auth import get_calendar_service
from src.utils.db_handler import get_db_connection, release_db_connection, get_user_by_email
from src.services.availability_engine import find_common_slots
from src.services.email_queue import queue_email
from src.services.notification import create_notification
from src.services.whatsapp_queue import queue_whatsapp


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _ensure_tz(dt: str) -> str:
    if dt and "Z" not in dt and "+" not in dt and dt.count("-") == 2:
        return dt + "Z"
    return dt


def _check_participant_conflicts(
    organizer_email: str,
    participant_emails: list,
    start_datetime: str,
    end_datetime: str,
) -> list:
    """
    Return a list of participant emails that are busy at the requested slot.
    Uses the organizer's credentials to call the FreeBusy API for all participants
    in one request (works for Google Workspace / calendars shared with the organizer).
    Fails open — returns [] if the API call errors, so scheduling isn't blocked.
    """
    try:
        service = get_calendar_service(user_email=organizer_email)
        body = {
            "timeMin": _ensure_tz(start_datetime),
            "timeMax": _ensure_tz(end_datetime),
            "items":   [{"id": e} for e in participant_emails],
        }
        freebusy = service.freebusy().query(body=body).execute()
        return [
            email for email in participant_emails
            if freebusy.get("calendars", {}).get(email, {}).get("busy")
        ]
    except Exception:
        return []


def _get_alternative_slots(
    organizer_email: str,
    participant_emails: list,
    start_datetime: str,
    end_datetime: str,
) -> list:
    """Return up to 3 common free slots in a ±2-day window around the requested time."""
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


def _build_rrule(recurrence: dict) -> Optional[str]:
    """
    Translate a recurrence dict into a Google Calendar RRULE string.

    Expected dict format:
        {
            "frequency": "WEEKLY",          # DAILY | WEEKLY | MONTHLY
            "interval":  1,                 # optional, default 1
            "count":     10,                # optional, number of occurrences
            "days":      ["MO", "WE"]       # optional, for WEEKLY
        }
    """
    freq = recurrence.get("frequency", "").upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY"):
        return None

    parts = [f"RRULE:FREQ={freq}"]
    if recurrence.get("interval"):
        parts.append(f"INTERVAL={recurrence['interval']}")
    if recurrence.get("count"):
        parts.append(f"COUNT={recurrence['count']}")
    if recurrence.get("days") and freq == "WEEKLY":
        parts.append(f"BYDAY={','.join(recurrence['days'])}")

    return ";".join(parts)


def _persist_meeting_to_db(
    meeting_id: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    organizer_email: str,
    meet_link: Optional[str],
    participants: list,
):
    """Write (or upsert) the meeting and its participants to local DB. Non-fatal."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO meetings (meeting_id, title, start_time, end_time, organizer_email, meet_link)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (meeting_id) DO UPDATE
                SET title          = EXCLUDED.title,
                    start_time     = EXCLUDED.start_time,
                    end_time       = EXCLUDED.end_time,
                    meet_link      = EXCLUDED.meet_link
            RETURNING id;
            """,
            (meeting_id, title, start_datetime, end_datetime, organizer_email, meet_link),
        )
        row = cur.fetchone()
        if row:
            meeting_pk = row["id"]
            cur.execute("DELETE FROM meeting_participants WHERE meeting_id = %s;", (meeting_pk,))
            for p in participants:
                if p.get("email"):
                    cur.execute(
                        """
                        INSERT INTO meeting_participants (meeting_id, participant_name, participant_email)
                        VALUES (%s, %s, %s);
                        """,
                        (meeting_pk, p.get("name", ""), p["email"]),
                    )
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"[meeting_creator] DB persist failed (non-fatal): {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            release_db_connection(conn)


def _send_meeting_notifications(
    participant_emails: list,
    notification_type: str,
    meeting_details: dict,
):
    """
    Queue plain-text email + create in-app notification for every participant.
    notification_type: "invite" | "update" | "cancel"
    """
    subject_map = {
        "invite": f"Meeting Invitation: {meeting_details.get('title')}",
        "update": f"Meeting Updated: {meeting_details.get('title')}",
        "cancel": f"Meeting Cancelled: {meeting_details.get('title')}",
    }
    subject = subject_map.get(notification_type, f"Meeting: {meeting_details.get('title')}")
    body = (
        f"{notification_type.capitalize()}: {meeting_details.get('title')}\n"
        f"Start    : {meeting_details.get('start')}\n"
        f"End      : {meeting_details.get('end')}\n"
        f"Link     : {meeting_details.get('link', 'N/A')}\n"
        f"Organizer: {meeting_details.get('organizer')}"
    )

    for email in participant_emails:
        try:
            queue_email(to_addr=email, subject=subject, body=body)
        except Exception as e:
            print(f"[meeting_creator] Email queue failed for {email}: {e}")

        user = None
        try:
            user = get_user_by_email(email)
            if user:
                create_notification(
                    user_id=user["id"],
                    message=f"{notification_type.capitalize()}: \"{meeting_details.get('title')}\" at {meeting_details.get('start')}",
                    notification_type=notification_type,
                )
        except Exception as e:
            print(f"[meeting_creator] In-app notification failed for {email}: {e}")

        if user and user.get("phone_number"):
            try:
                queue_whatsapp(user["phone_number"], body,
                               metadata={"channel": "meeting", "type": notification_type})
            except Exception as e:
                print(f"[meeting_creator] WhatsApp queue failed for {email}: {e}")


def _schedule_reminders(
    meeting_id: str,
    title: str,
    start_datetime: str,
    participant_emails: list,
):
    """Schedule Celery reminder tasks at 24h and 1h before the meeting."""
    try:
        from src.worker import send_reminder_24h, send_reminder_1h

        start = datetime.fromisoformat(start_datetime.replace("Z", ""))
        now   = datetime.utcnow()

        eta_24h = start - timedelta(hours=24)
        eta_1h  = start - timedelta(hours=1)

        if eta_24h > now:
            send_reminder_24h.apply_async(
                args=[meeting_id, title, start_datetime, participant_emails],
                eta=eta_24h,
            )
        if eta_1h > now:
            send_reminder_1h.apply_async(
                args=[meeting_id, title, start_datetime, participant_emails],
                eta=eta_1h,
            )
    except Exception as e:
        print(f"[meeting_creator] Reminder scheduling failed (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_meeting(
    title: str,
    start_datetime: str,
    end_datetime: str,
    participant_names: list,
    scheduler_email: str,
    recurrence: Optional[dict] = None,
) -> dict:
    """
    Create a new Google Calendar event.

    Parameters
    ----------
    title             : meeting title
    start_datetime    : ISO 8601 start datetime
    end_datetime      : ISO 8601 end datetime
    participant_names : display names resolved via DB fuzzy search
    scheduler_email   : organiser's email (auth + conflict check)
    recurrence        : optional recurrence rule dict, e.g.
                        {"frequency": "WEEKLY", "count": 10, "days": ["MO", "WE"]}

    On conflict the response includes:
      "suggested_alternatives": [{start, end}, ...]   (up to 3 slots)

    On participant unavailability:
      "blocked_participants": [email, ...]
      "suggested_alternatives": [{start, end}, ...]
    """

    try:
        # 1. Resolve display names → emails
        participants      = resolve_participants(participant_names)
        participant_emails = [p["email"] for p in participants if p.get("email")]

        # 2. Organiser conflict check
        conflict = check_scheduler_conflict(scheduler_email, start_datetime, end_datetime)
        if conflict:
            alternatives = _get_alternative_slots(
                scheduler_email, participant_emails, start_datetime, end_datetime
            )
            return {
                "success": False,
                "error":                 "Conflict detected: scheduler is busy at the requested time",
                "suggested_alternatives": alternatives,
            }

        # 3. Participant availability check (Feature 3)
        if participant_emails:
            blocked = _check_participant_conflicts(
                scheduler_email, participant_emails, start_datetime, end_datetime
            )
            if blocked:
                alternatives = _get_alternative_slots(
                    scheduler_email, participant_emails, start_datetime, end_datetime
                )
                return {
                    "success": False,
                    "error":                 f"Participants unavailable: {', '.join(blocked)}",
                    "blocked_participants":   blocked,
                    "suggested_alternatives": alternatives,
                }

        # 4. Build Google Calendar event body
        service    = get_calendar_service(user_email=scheduler_email)
        event_body = {
            "summary":  title,
            "start":    {"dateTime": start_datetime},
            "end":      {"dateTime": end_datetime},
            "attendees": [{"email": e} for e in participant_emails],
            "conferenceData": {
                "createRequest": {"requestId": f"sam-{title[:10]}"}
            },
        }

        # Feature 7: Recurring meetings
        if recurrence:
            rrule = _build_rrule(recurrence)
            if rrule:
                event_body["recurrence"] = [rrule]

        # 5. Insert into Google Calendar
        event      = service.events().insert(
            calendarId="primary",
            body=event_body,
            conferenceDataVersion=1,
        ).execute()

        meeting_id = event.get("id")
        meet_link  = event.get("hangoutLink")

        # Feature 9: Persist to local DB
        _persist_meeting_to_db(
            meeting_id, title, start_datetime, end_datetime,
            scheduler_email, meet_link, participants,
        )

        # Feature 2: Auto-notifications
        _send_meeting_notifications(
            participant_emails, "invite",
            {
                "title":     title,
                "start":     start_datetime,
                "end":       end_datetime,
                "link":      meet_link,
                "organizer": scheduler_email,
            },
        )

        # Feature 6: Schedule reminders
        _schedule_reminders(meeting_id, title, start_datetime, participant_emails)

        return {
            "success":     True,
            "meeting_id":  meeting_id,
            "event_link":  event.get("htmlLink"),
            "meet_link":   meet_link,
            "participants": participant_emails,
            "start":       start_datetime,
            "end":         end_datetime,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
