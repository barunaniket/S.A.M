import os
from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "sam_worker",
    broker=redis_url,
    backend=redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
)


@celery_app.task(name="test_task")
def test_task(word: str):
    return f"Celery received: {word}"


# ---------------------------------------------------------------------------
# WhatsApp send task — used by broadcast_service / notification_dispatcher when
# fan-out volume justifies dedicated workers instead of the polling queue.
# ---------------------------------------------------------------------------

@celery_app.task(name="send_whatsapp", bind=True, max_retries=3)
def send_whatsapp(self, to_phone: str, body: str):
    from src.services.whatsapp_service import send_text

    result = send_text(to_phone=to_phone, body=body)
    if not result.get("success"):
        raise self.retry(
            exc=RuntimeError(result.get("error") or "WhatsApp send failed"),
            countdown=min(2 ** self.request.retries, 30),
        )
    return result


# ---------------------------------------------------------------------------
# Lightweight-meeting reminders (upload-driven flow). Unlike the email-only
# reminder tasks above, these take the full attendee list inline (name/email/
# phone) — no DB lookup needed, so students who aren't in `users` still get
# pinged.
# ---------------------------------------------------------------------------

def _format_lite_reminder(window: str, title: str, start_time: str,
                           location: str) -> str:
    when_label = "tomorrow" if window == "24h" else "in 1 hour"
    parts = [
        f"Reminder: \"{title}\" is {when_label}.",
        f"Starts at {start_time}.",
    ]
    if location:
        parts.append(f"Location: {location}.")
    parts.append("Please be on time.")
    return "\n".join(parts)


def _send_lite_reminder(window: str, meeting_id, title: str,
                        start_time: str, location: str,
                        attendees: list) -> str:
    from src.services.email_queue import queue_email
    from src.services.whatsapp_queue import queue_whatsapp

    body = _format_lite_reminder(window, title, start_time, location)
    subject = f"Reminder: \"{title}\" is " + ("tomorrow" if window == "24h" else "starting in 1 hour")

    sent_email = sent_wa = 0
    for a in attendees or []:
        email = a.get("email")
        phone = a.get("phone")

        if email:
            try:
                queue_email(to_addr=email, subject=subject, body=body,
                            metadata={"channel": "meeting_lite",
                                      "type": f"reminder_{window}",
                                      "meeting_id": meeting_id})
                sent_email += 1
            except Exception as e:
                print(f"[reminder_lite_{window}] email queue failed for {email}: {e}")

        if phone:
            try:
                queue_whatsapp(phone, body, metadata={
                    "channel":    "meeting_lite",
                    "type":       f"reminder_{window}",
                    "intent":     "reminder",
                    "meeting_id": meeting_id,
                })
                sent_wa += 1
            except Exception as e:
                print(f"[reminder_lite_{window}] whatsapp queue failed for {phone}: {e}")

    return f"{window} lite reminder for meeting {meeting_id}: {sent_email} email, {sent_wa} whatsapp"


@celery_app.task(name="send_meeting_lite_reminder_24h")
def send_meeting_lite_reminder_24h(meeting_id, title: str,
                                    start_time: str, location: str,
                                    attendees: list):
    return _send_lite_reminder("24h", meeting_id, title, start_time,
                                location, attendees)


@celery_app.task(name="send_meeting_lite_reminder_1h")
def send_meeting_lite_reminder_1h(meeting_id, title: str,
                                   start_time: str, location: str,
                                   attendees: list):
    return _send_lite_reminder("1h", meeting_id, title, start_time,
                                location, attendees)


# ---------------------------------------------------------------------------
# Feature 6: Meeting reminder tasks
# ---------------------------------------------------------------------------

@celery_app.task(name="send_reminder_24h")
def send_reminder_24h(
    meeting_id: str,
    title: str,
    start_time: str,
    participant_emails: list,
):
    """
    Queue a 24-hour reminder email + WhatsApp to all meeting participants.
    Scheduled with eta = meeting_start - 24h from meeting_creator.
    """
    from src.services.email_queue import queue_email
    from src.services.whatsapp_queue import queue_whatsapp
    from src.utils.db_handler import get_user_by_email

    subject = f"Reminder: \"{title}\" is tomorrow"
    body = (
        f"This is a reminder that the following meeting is scheduled for tomorrow.\n\n"
        f"Meeting : {title}\n"
        f"Time    : {start_time}\n\n"
        f"Please check your Google Calendar for the meeting link."
    )

    for email in participant_emails:
        try:
            queue_email(to_addr=email, subject=subject, body=body)
        except Exception as e:
            print(f"[reminder_24h] Failed to queue email for {email}: {e}")

        try:
            user = get_user_by_email(email)
            if user and user.get("phone_number"):
                queue_whatsapp(
                    user["phone_number"],
                    body,
                    metadata={
                        "channel":    "reminder",
                        "type":       "reminder_24h",
                        "intent":     "reminder",
                        "meeting_id": meeting_id,
                        "org_id":     user.get("org_id"),
                        "user_id":    user.get("id"),
                    },
                )
        except Exception as e:
            print(f"[reminder_24h] WhatsApp queue failed for {email}: {e}")

    return f"24h reminders queued for meeting {meeting_id}"


@celery_app.task(name="send_reminder_1h")
def send_reminder_1h(
    meeting_id: str,
    title: str,
    start_time: str,
    participant_emails: list,
):
    """
    1-hour reminder: in-app notification + WhatsApp ping to every participant
    who has a phone_number on file.
    Scheduled with eta = meeting_start - 1h from meeting_creator.
    """
    from src.services.notification import create_notification
    from src.services.whatsapp_queue import queue_whatsapp
    from src.utils.db_handler import get_user_by_email

    short_msg = f"Reminder: \"{title}\" starts in 1 hour at {start_time}"

    for email in participant_emails:
        user = None
        try:
            user = get_user_by_email(email)
            if user:
                create_notification(
                    user_id=user["id"],
                    message=short_msg,
                    notification_type="reminder",
                )
        except Exception as e:
            print(f"[reminder_1h] Failed in-app notification for {email}: {e}")

        if user and user.get("phone_number"):
            try:
                queue_whatsapp(
                    user["phone_number"],
                    short_msg,
                    metadata={
                        "channel":    "reminder",
                        "type":       "reminder_1h",
                        "intent":     "reminder",
                        "meeting_id": meeting_id,
                        "org_id":     user.get("org_id"),
                        "user_id":    user.get("id"),
                    },
                )
            except Exception as e:
                print(f"[reminder_1h] WhatsApp queue failed for {email}: {e}")

    return f"1h reminders sent for meeting {meeting_id}"
