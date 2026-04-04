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
    Queue a 24-hour reminder email to all meeting participants.
    Scheduled with eta = meeting_start - 24h from meeting_creator.
    """
    from src.services.email_queue import queue_email

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

    return f"24h reminders queued for meeting {meeting_id}"


@celery_app.task(name="send_reminder_1h")
def send_reminder_1h(
    meeting_id: str,
    title: str,
    start_time: str,
    participant_emails: list,
):
    """
    Create in-app notifications for all participants 1 hour before the meeting.
    Scheduled with eta = meeting_start - 1h from meeting_creator.
    """
    from src.utils.db_handler import get_user_by_email
    from src.services.notification import create_notification

    for email in participant_emails:
        try:
            user = get_user_by_email(email)
            if user:
                create_notification(
                    user_id=user["id"],
                    message=f"Reminder: \"{title}\" starts in 1 hour at {start_time}",
                    notification_type="reminder",
                )
        except Exception as e:
            print(f"[reminder_1h] Failed in-app notification for {email}: {e}")

    return f"1h reminders sent for meeting {meeting_id}"
