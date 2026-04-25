"""
meeting_lite.py
---------------
Upload-driven meeting flow used by the WhatsApp orchestrator. Unlike
meeting_creator (Google-Calendar-backed), this never writes anyone's
calendar. It:

  1. Persists a row in `lightweight_meetings`
  2. Generates an ICS file the organizer (and recipients) can save manually
  3. Sends email + WhatsApp invites — ICS is attached to email only
  4. Schedules Celery 24h / 1h reminders against the attendee snapshot

Attendees are passed inline (list of dicts with email/phone/name) rather
than looked up in `users`, because most are students who may not have a
DB account.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytz

from src.services.email_queue import queue_email
from src.services.whatsapp_queue import queue_whatsapp
from src.utils.db_handler import get_db_connection, release_db_connection
from src.utils.ics_generator import generate_ics

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------

DEFAULT_TZ = pytz.timezone("Asia/Kolkata")


def _parse_iso(s: str) -> Optional[datetime]:
    """Parse an ISO-8601 string into a TZ-aware datetime (Asia/Kolkata if naive)."""
    if not s:
        return None
    raw = s.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        try:
            dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = DEFAULT_TZ.localize(dt)
    return dt


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _insert_meeting(org_id: int, organizer_id: Optional[int],
                    title: str, start_dt: datetime, end_dt: datetime,
                    location: Optional[str], agenda: Optional[str],
                    attendees: List[Dict[str, Any]],
                    ics_path: Optional[str],
                    upload_id: Optional[int]) -> int:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SET LOCAL app.org_id = %s;", (str(org_id),))
        cur.execute(
            """
            INSERT INTO lightweight_meetings
                (org_id, organizer_id, title, start_time, end_time,
                 location, agenda, attendees, ics_path, upload_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                org_id, organizer_id, title,
                start_dt.astimezone(timezone.utc).replace(tzinfo=None),
                end_dt.astimezone(timezone.utc).replace(tzinfo=None),
                location, agenda,
                json.dumps(attendees, default=str),
                ics_path, upload_id,
            ),
        )
        meeting_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        return meeting_id
    finally:
        release_db_connection(conn)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def _format_subject(title: str) -> str:
    return f"You're invited: {title}"


def _format_body(title: str, start_dt: datetime, end_dt: datetime,
                 location: Optional[str], agenda: Optional[str],
                 organizer_name: Optional[str]) -> str:
    when = start_dt.strftime("%A, %d %b %Y at %I:%M %p")
    until = end_dt.strftime("%I:%M %p")
    lines = [
        f"Hi,",
        f"You're invited to: {title}",
        f"When : {when}–{until}",
    ]
    if location:
        lines.append(f"Where: {location}")
    if agenda:
        lines.append(f"Agenda: {agenda}")
    if organizer_name:
        lines.append(f"From : {organizer_name}")
    lines.append("")
    lines.append("Please attend on time. A calendar (.ics) attachment is in your email.")
    return "\n".join(lines)


def _send_email_with_ics(to_addr: str, subject: str, body: str,
                         ics_path: Optional[str], meeting_id: int) -> None:
    """
    Queue an email job. The existing email_queue worker doesn't currently
    handle attachments, so we route ICS-bearing invites through the
    notification_dispatcher fallback (synchronous). For attendees without
    an ICS expectation, we just queue plain text.
    """
    if ics_path:
        try:
            from src.services.notification_dispatcher import send_meeting_notification
            # send_meeting_notification renders an HTML invite template + attaches ICS
            send_meeting_notification(
                recipient_email=to_addr,
                notification_type="invite",
                meeting_details={
                    "title":     subject.replace("You're invited: ", ""),
                    "start":     "",
                    "end":       "",
                    "link":      "",
                    "organizer": "",
                },
                ics_attachment=ics_path,
            )
            return
        except Exception:
            logger.exception("ICS email path failed; falling back to plain queue")
    queue_email(to_addr=to_addr, subject=subject, body=body,
                metadata={"channel": "meeting_lite", "meeting_id": meeting_id})


def _broadcast_invites(meeting_id: int, title: str,
                       start_dt: datetime, end_dt: datetime,
                       location: Optional[str], agenda: Optional[str],
                       attendees: List[Dict[str, Any]],
                       ics_path: Optional[str],
                       organizer_name: Optional[str],
                       org_id: Optional[int]) -> Dict[str, int]:
    subject = _format_subject(title)
    body    = _format_body(title, start_dt, end_dt, location, agenda, organizer_name)

    sent_email = 0
    sent_wa    = 0

    for a in attendees:
        email = a.get("email")
        phone = a.get("phone")

        if email:
            try:
                _send_email_with_ics(email, subject, body, ics_path, meeting_id)
                sent_email += 1
            except Exception:
                logger.exception("Email send failed for %s", email)

        if phone:
            try:
                queue_whatsapp(phone, body, metadata={
                    "channel":    "meeting_lite",
                    "type":       "invite",
                    "intent":     "meeting_invite",
                    "meeting_id": meeting_id,
                    "org_id":     org_id,
                })
                sent_wa += 1
            except Exception:
                logger.exception("WhatsApp queue failed for %s", phone)

    return {"email": sent_email, "whatsapp": sent_wa}


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

def _schedule_reminders(meeting_id: int, title: str, start_dt: datetime,
                        location: Optional[str],
                        attendees: List[Dict[str, Any]]) -> None:
    """
    Schedule Celery 24h + 1h reminder tasks. Best-effort — failure to enqueue
    doesn't block the invite send.
    """
    try:
        from src.worker import (
            send_meeting_lite_reminder_1h,
            send_meeting_lite_reminder_24h,
        )

        now = datetime.now(timezone.utc)
        eta_24h = start_dt - timedelta(hours=24)
        eta_1h  = start_dt - timedelta(hours=1)

        loc = location or ""
        if eta_24h > now:
            send_meeting_lite_reminder_24h.apply_async(
                args=[meeting_id, title, start_dt.isoformat(), loc, attendees],
                eta=eta_24h,
            )
        if eta_1h > now:
            send_meeting_lite_reminder_1h.apply_async(
                args=[meeting_id, title, start_dt.isoformat(), loc, attendees],
                eta=eta_1h,
            )
    except Exception:
        logger.exception("Reminder scheduling failed (non-fatal)")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_meeting_lite(org_id: int,
                        organizer_id: Optional[int],
                        organizer_name: Optional[str],
                        organizer_email: Optional[str],
                        title: str,
                        start_time: str,
                        end_time: Optional[str],
                        attendees: List[Dict[str, Any]],
                        location: Optional[str] = None,
                        agenda: Optional[str] = None,
                        upload_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Persist + invite + schedule reminders for an upload-driven meeting.
    Returns:
        {success, meeting_id, counts: {email, whatsapp}, ics_path,
         start, end, attendee_count}
    """
    if not title or not title.strip():
        return {"success": False, "message": "Meeting title is required."}

    start_dt = _parse_iso(start_time)
    if not start_dt:
        return {"success": False, "message": "Couldn't parse meeting start time."}

    end_dt = _parse_iso(end_time) if end_time else None
    if not end_dt:
        end_dt = start_dt + timedelta(hours=1)
    if end_dt <= start_dt:
        return {"success": False, "message": "Meeting end must be after start."}

    if not attendees:
        return {"success": False, "message": "No attendees to invite."}

    # Generate an ICS file we can attach to outbound emails.
    ics_path: Optional[str] = None
    try:
        ics_attendees = [
            {"name": a.get("name") or a.get("email") or "Attendee",
             "email": a.get("email") or "noreply@sam.local"}
            for a in attendees if a.get("email")
        ]
        ics_path = generate_ics(
            title=title,
            start_dt=start_dt,
            end_dt=end_dt,
            organizer={"name": organizer_name or "S.A.M.",
                        "email": organizer_email or "sam@local"},
            attendees=ics_attendees,
        )
    except Exception:
        logger.exception("ICS generation failed (continuing without attachment)")

    try:
        meeting_id = _insert_meeting(
            org_id, organizer_id, title, start_dt, end_dt,
            location, agenda, attendees, ics_path, upload_id,
        )
    except Exception as e:
        logger.exception("Persist failed")
        return {"success": False, "message": f"Could not save meeting: {e}"}

    counts = _broadcast_invites(
        meeting_id, title, start_dt, end_dt, location, agenda,
        attendees, ics_path, organizer_name, org_id,
    )

    _schedule_reminders(meeting_id, title, start_dt, location, attendees)

    return {
        "success":         True,
        "meeting_id":      meeting_id,
        "counts":          counts,
        "ics_path":        ics_path,
        "start":           start_dt.isoformat(),
        "end":             end_dt.isoformat(),
        "attendee_count":  len(attendees),
        "message": (
            f"Scheduled '{title}' for "
            f"{start_dt.strftime('%a %d %b, %I:%M %p')}. "
            f"Invited {len(attendees)} people "
            f"({counts['email']} via email, {counts['whatsapp']} via WhatsApp). "
            f"24h + 1h reminders queued."
        ),
    }
