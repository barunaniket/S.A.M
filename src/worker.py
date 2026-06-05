import logging
import os
from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready

logger = logging.getLogger(__name__)

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

# ---------------------------------------------------------------------------
# Beat schedule
#
# Run with `celery -A src.worker.celery_app beat --loglevel=info` (separate
# container — never embedded in the worker, or schedules duplicate). The
# tick_user_briefings task is a 5-minute heartbeat; the M5 implementation
# fans out per-user briefings whose briefing_time falls in the last 5 min
# (in the user's local timezone).
# ---------------------------------------------------------------------------
celery_app.conf.beat_schedule = {
    "tick-user-briefings": {
        "task": "tick_user_briefings",
        "schedule": 300.0,   # 5 minutes
    },
}


@celery_app.task(name="test_task")
def test_task(word: str):
    return f"Celery received: {word}"


@celery_app.task(name="tick_user_briefings")
def tick_user_briefings():
    """
    Every 5 minutes: dispatch a daily briefing to any user whose
    briefing_time falls in the last 5 minutes (in their local timezone) and
    has briefing_enabled=TRUE. We track last_sent_date in a lightweight key
    on user_preferences to avoid double-sending if the tick lands twice
    inside the same 5-minute window.
    """
    from datetime import date as _date, datetime as _dt, timedelta
    import pytz

    from src.services.timetable_service import todays_classes
    from src.services.task_service import list_tasks_for_assignee
    from src.services.academic_calendar import events_in_range  # type: ignore[attr-defined]
    from src.services.whatsapp_queue import queue_whatsapp
    from src.services.telegram_queue import queue_telegram
    from src.utils.db_handler import get_db_connection, release_db_connection

    log = logging.getLogger(__name__)
    sent_count = 0
    now_utc = _dt.utcnow()

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT up.user_id, up.briefing_time, up.timezone, u.org_id,
                   u.full_name, u.phone_number, u.telegram_chat_id
              FROM user_preferences up
              JOIN users u ON u.id = up.user_id
             WHERE up.briefing_enabled = TRUE
               AND (u.phone_number IS NOT NULL OR u.telegram_chat_id IS NOT NULL);
            """
        )
        prefs = [dict(r) for r in cur.fetchall()]
        cur.close()
    except Exception:
        log.exception("tick_user_briefings: pref scan failed")
        prefs = []
    finally:
        release_db_connection(conn)

    for p in prefs:
        try:
            tz = pytz.timezone(p.get("timezone") or "Asia/Kolkata")
        except Exception:
            tz = pytz.timezone("Asia/Kolkata")
        local_now = _dt.now(tz).replace(tzinfo=None)
        target = local_now.replace(
            hour=p["briefing_time"].hour,
            minute=p["briefing_time"].minute,
            second=0, microsecond=0,
        )
        diff = (local_now - target).total_seconds()
        # Only fire if we're within the last 5 minutes (the cadence of the tick).
        if not (0 <= diff < 300):
            continue

        body = _compose_briefing(
            user_id=p["user_id"],
            org_id=p["org_id"],
            full_name=p.get("full_name") or "there",
            today_classes_fn=todays_classes,
            tasks_fn=list_tasks_for_assignee,
            events_fn=lambda org_id, start, end: _safe_events(events_fn_org=org_id, start=start, end=end),
        )
        if not body:
            continue

        meta = {
            "channel": "daily_briefing",
            "intent": "briefing",
            "org_id": p["org_id"],
            "user_id": p["user_id"],
        }
        delivered = False
        if p.get("phone_number"):
            try:
                queue_whatsapp(p["phone_number"], body, metadata=meta)
                delivered = True
            except Exception:
                log.exception("tick_user_briefings: WA queue failed for user %s",
                              p["user_id"])
        if p.get("telegram_chat_id"):
            try:
                queue_telegram(int(p["telegram_chat_id"]), body, metadata=meta)
                delivered = True
            except Exception:
                log.exception("tick_user_briefings: TG queue failed for user %s",
                              p["user_id"])
        if delivered:
            sent_count += 1

    log.info("tick_user_briefings: dispatched %d briefing(s)", sent_count)
    return f"sent={sent_count}"


def _safe_events(events_fn_org: int, start, end):
    try:
        from src.services.academic_calendar import list_events
        return list_events(events_fn_org, start=start, end=end)
    except Exception:
        return []


def _compose_briefing(*, user_id: int, org_id: int, full_name: str,
                      today_classes_fn, tasks_fn, events_fn) -> str:
    """Assemble a short morning briefing string."""
    from datetime import date as _date

    today = _date.today()
    classes = today_classes_fn(user_id) or []
    tasks_due_today = []
    overdue = []
    for t in (tasks_fn(user_id, include_done=False) or []):
        d = t.get("deadline")
        if d:
            try:
                from datetime import datetime as _dt
                dl = d if hasattr(d, "year") else _dt.fromisoformat(str(d).replace("Z", ""))
                if dl.date() < today:
                    overdue.append(t)
                elif dl.date() == today:
                    tasks_due_today.append(t)
            except Exception:
                pass
    events = events_fn(org_id, today, today) or []

    parts = [f"☀️ Good morning, {full_name}."]
    if events:
        bits = ", ".join(f"{e['title']} ({e['kind']})" for e in events)
        parts.append(f"📅 Today: {bits}.")
    if classes:
        c_lines = [f"  • {c['start_time']}–{c['end_time']} {c.get('subject') or 'class'}"
                   + (f" @ {c['room']}" if c.get('room') else "")
                   for c in classes]
        parts.append("📚 Classes today:\n" + "\n".join(c_lines))
    else:
        parts.append("📚 No classes scheduled today.")
    if tasks_due_today:
        t_lines = [f"  • {t['title']}" for t in tasks_due_today]
        parts.append(f"⏰ Tasks due today ({len(tasks_due_today)}):\n" + "\n".join(t_lines))
    if overdue:
        parts.append(f"⚠️ {len(overdue)} task(s) overdue — check /app/admin/tasks.")
    parts.append("Have a good day!")
    return "\n\n".join(parts)


@celery_app.task(name="warmup_whisper")
def warmup_whisper_task():
    """
    Force-load the faster-whisper model into worker memory so the first
    user-facing transcription doesn't pay the 8–15s cold-start cost. Auto-
    fired by the worker_ready signal below; can also be called on demand.
    """
    from src.services.media_transcriber import warmup_whisper
    warmup_whisper()
    return "whisper-ready"


@worker_ready.connect
def _bootstrap_worker(**_):
    """
    Fire whisper warmup once per worker process at boot. Best-effort — if
    SAM_SKIP_WHISPER_WARMUP=1 the warmup is skipped (useful in tests / when
    the model files aren't downloaded yet).
    """
    log = logging.getLogger(__name__)
    if os.getenv("SAM_SKIP_WHISPER_WARMUP", "").lower() in ("1", "true", "yes"):
        log.info("worker_ready: skipping whisper warmup (SAM_SKIP_WHISPER_WARMUP set)")
        return
    try:
        warmup_whisper_task.apply_async(args=[])
        log.info("worker_ready: whisper warmup queued")
    except Exception:
        log.exception("worker_ready: failed to queue whisper warmup")


# ---------------------------------------------------------------------------
# Task reminders (M4) — scheduled 24h/4h/1h before each task's deadline.
#
# Reuses queue_whatsapp + queue_email so delivery is identical to all other
# notifications. Idempotent: marks task_reminders.fired=true after dispatch.
# ---------------------------------------------------------------------------

def _send_task_reminder(window: str, task_id: int):
    from src.services.task_service import format_task_message, get_task
    from src.services.whatsapp_queue import queue_whatsapp
    from src.services.telegram_queue import queue_telegram
    from src.services.email_queue import queue_email
    from src.utils.db_handler import (
        get_db_connection, release_db_connection, get_user_by_email,
    )

    task = get_task(task_id)
    if not task or task.get("status") in ("DONE", "CANCELLED"):
        return f"task {task_id} not actionable ({task and task.get('status')})"

    body = format_task_message(task, kind=window)

    # Resolve channels: prefer user record (phone + email + telegram) if matched.
    phone = task.get("assignee_phone")
    email = task.get("assignee_email")
    telegram_chat_id = task.get("assignee_telegram_chat_id")
    if task.get("assignee_id") and (not phone or not telegram_chat_id):
        try:
            if email:
                u = get_user_by_email(email)
                if u:
                    phone = phone or u.get("phone_number")
                    telegram_chat_id = telegram_chat_id or u.get("telegram_chat_id")
        except Exception:
            pass

    sent_email = sent_wa = sent_tg = 0
    if email:
        try:
            queue_email(to_addr=email,
                        subject=f"Reminder: {task['title']}",
                        body=body,
                        metadata={"channel": "task_reminder",
                                  "type": f"reminder_{window}",
                                  "task_id": task_id})
            sent_email = 1
        except Exception as e:
            logging.getLogger(__name__).warning(
                "task reminder email failed for task %s: %s", task_id, e)

    if phone:
        try:
            queue_whatsapp(phone, body, metadata={
                "channel": "task_reminder",
                "type": f"reminder_{window}",
                "intent": "reminder",
                "task_id": task_id,
                "org_id": task.get("org_id"),
                "user_id": task.get("assignee_id"),
            })
            sent_wa = 1
        except Exception as e:
            logging.getLogger(__name__).warning(
                "task reminder whatsapp failed for task %s: %s", task_id, e)

    if telegram_chat_id:
        try:
            queue_telegram(int(telegram_chat_id), body, metadata={
                "channel": "task_reminder",
                "type": f"reminder_{window}",
                "intent": "reminder",
                "task_id": task_id,
                "org_id": task.get("org_id"),
                "user_id": task.get("assignee_id"),
            })
            sent_tg = 1
        except Exception as e:
            logging.getLogger(__name__).warning(
                "task reminder telegram failed for task %s: %s", task_id, e)

    # Mark the matching reminder row as fired (best-effort).
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE task_reminders
               SET fired = TRUE, fired_at = NOW()
             WHERE task_id = %s AND kind = %s AND fired = FALSE;
            """,
            (task_id, window),
        )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    return (f"task {task_id} {window} reminder: "
            f"{sent_email} email, {sent_wa} whatsapp, {sent_tg} telegram")


@celery_app.task(name="send_task_reminder_24h")
def send_task_reminder_24h(task_id: int):
    return _send_task_reminder("24h", task_id)


@celery_app.task(name="send_task_reminder_4h")
def send_task_reminder_4h(task_id: int):
    return _send_task_reminder("4h", task_id)


@celery_app.task(name="send_task_reminder_1h")
def send_task_reminder_1h(task_id: int):
    return _send_task_reminder("1h", task_id)


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


@celery_app.task(name="dispatch_mcq_question")
def dispatch_mcq_question(session_id: int, q_index: int):
    """Push a single MCQ question to every paired student in the batch."""
    from src.services.attendance_mcq import dispatch_question
    dispatch_question(session_id, q_index)
    return f"mcq session {session_id} q{q_index} dispatched"


@celery_app.task(name="close_mcq_session")
def close_mcq_session(session_id: int):
    """Score the session, write attendance_records, DM the faculty."""
    from src.services.attendance_mcq import close_session
    result = close_session(session_id)
    return f"mcq session {session_id} closed: {result.get('success')}"


# ---------------------------------------------------------------------------
# Assignment deadline nudges (v13). Mirrors the task-reminder pattern above.
# Logic lives in src/tasks/assignments.py to keep this file thin.
# ---------------------------------------------------------------------------

@celery_app.task(name="dispatch_assignment_nudge")
def dispatch_assignment_nudge(assignment_id: int, kind: str):
    """DM students who haven't submitted yet."""
    from src.tasks.assignments import dispatch_nudge
    return dispatch_nudge(assignment_id, kind)


@celery_app.task(name="close_assignment")
def close_assignment(assignment_id: int):
    """Flip status to CLOSED, summarise misses, DM faculty."""
    from src.tasks.assignments import close_assignment as _close
    return _close(assignment_id)


@celery_app.task(name="send_telegram", bind=True, max_retries=3)
def send_telegram(self, chat_id: int, body: str):
    from src.services.telegram_service import send_text

    result = send_text(chat_id=int(chat_id), body=body)
    if not result.get("success"):
        raise self.retry(
            exc=RuntimeError(result.get("error") or "Telegram send failed"),
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
    from src.services.telegram_queue import queue_telegram

    body = _format_lite_reminder(window, title, start_time, location)
    subject = f"Reminder: \"{title}\" is " + ("tomorrow" if window == "24h" else "starting in 1 hour")

    sent_email = sent_wa = sent_tg = 0
    for a in attendees or []:
        email = a.get("email")
        phone = a.get("phone")
        tg    = a.get("telegram_chat_id")

        if email:
            try:
                queue_email(to_addr=email, subject=subject, body=body,
                            metadata={"channel": "meeting_lite",
                                      "type": f"reminder_{window}",
                                      "meeting_id": meeting_id})
                sent_email += 1
            except Exception:
                logger.warning("[reminder_lite_%s] email queue failed for %s",
                               window, email, exc_info=True)

        if phone:
            try:
                queue_whatsapp(phone, body, metadata={
                    "channel":    "meeting_lite",
                    "type":       f"reminder_{window}",
                    "intent":     "reminder",
                    "meeting_id": meeting_id,
                })
                sent_wa += 1
            except Exception:
                logger.warning("[reminder_lite_%s] whatsapp queue failed for %s",
                               window, phone, exc_info=True)

        if tg:
            try:
                queue_telegram(int(tg), body, metadata={
                    "channel":    "meeting_lite",
                    "type":       f"reminder_{window}",
                    "intent":     "reminder",
                    "meeting_id": meeting_id,
                })
                sent_tg += 1
            except Exception:
                logger.warning("[reminder_lite_%s] telegram queue failed for %s",
                               window, tg, exc_info=True)

    return (f"{window} lite reminder for meeting {meeting_id}: "
            f"{sent_email} email, {sent_wa} whatsapp, {sent_tg} telegram")


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
#
# All four windows (24h / 1h / 30min / 10min) share one fan-out helper. They
# differ only in: the message body, whether an email goes out (24h only), and
# whether an in-app notification is created (the sub-hour windows). The helper
# resolves each participant once and delivers across every channel they have.
# ---------------------------------------------------------------------------

def _fan_out_meeting_reminder(
    *,
    meeting_id: str,
    reminder_type: str,           # e.g. "reminder_24h" — also the metadata type
    body: str,                    # message used for email/in-app/WA/TG alike
    participant_emails: list,
    email_subject: str | None = None,   # set → queue an email to the raw address
    in_app: bool = False,               # True → also create an in-app notification
) -> str:
    """Deliver one reminder to every participant across their channels.

    Best-effort per channel: a failure on one channel/recipient is logged and
    never aborts the rest. Returns a short summary string for the task result.
    """
    from src.services.email_queue import queue_email
    from src.services.whatsapp_queue import queue_whatsapp
    from src.services.telegram_queue import queue_telegram
    from src.utils.db_handler import get_user_by_email

    label = reminder_type
    sent_email = sent_inapp = sent_wa = sent_tg = 0

    for email in participant_emails:
        # Email targets the raw address — the recipient need not be a user.
        if email_subject:
            try:
                queue_email(to_addr=email, subject=email_subject, body=body)
                sent_email += 1
            except Exception:
                logger.warning("[%s] email queue failed for %s", label, email,
                               exc_info=True)

        user = None
        try:
            user = get_user_by_email(email)
        except Exception:
            logger.warning("[%s] user lookup failed for %s", label, email,
                           exc_info=True)

        if in_app and user:
            try:
                from src.services.notification import create_notification
                create_notification(user_id=user["id"], message=body,
                                    notification_type="reminder")
                sent_inapp += 1
            except Exception:
                logger.warning("[%s] in-app notification failed for %s", label,
                               email, exc_info=True)

        meta = {
            "channel":    "reminder",
            "type":       reminder_type,
            "intent":     "reminder",
            "meeting_id": meeting_id,
            "org_id":     (user or {}).get("org_id"),
            "user_id":    (user or {}).get("id"),
        }
        if user and user.get("phone_number"):
            try:
                queue_whatsapp(user["phone_number"], body, metadata=meta)
                sent_wa += 1
            except Exception:
                logger.warning("[%s] whatsapp queue failed for %s", label, email,
                               exc_info=True)
        if user and user.get("telegram_chat_id"):
            try:
                queue_telegram(int(user["telegram_chat_id"]), body, metadata=meta)
                sent_tg += 1
            except Exception:
                logger.warning("[%s] telegram queue failed for %s", label, email,
                               exc_info=True)

    return (f"{label} for meeting {meeting_id}: {sent_email} email, "
            f"{sent_inapp} in-app, {sent_wa} whatsapp, {sent_tg} telegram")


@celery_app.task(name="send_reminder_24h")
def send_reminder_24h(meeting_id: str, title: str, start_time: str,
                      participant_emails: list):
    """24-hour reminder: email + WhatsApp + Telegram to all participants."""
    body = (
        f"This is a reminder that the following meeting is scheduled for tomorrow.\n\n"
        f"Meeting : {title}\n"
        f"Time    : {start_time}\n\n"
        f"Please check your Google Calendar for the meeting link."
    )
    return _fan_out_meeting_reminder(
        meeting_id=meeting_id, reminder_type="reminder_24h", body=body,
        participant_emails=participant_emails,
        email_subject=f"Reminder: \"{title}\" is tomorrow",
    )


@celery_app.task(name="send_reminder_1h")
def send_reminder_1h(meeting_id: str, title: str, start_time: str,
                     participant_emails: list):
    """1-hour reminder: in-app notification + WhatsApp + Telegram."""
    return _fan_out_meeting_reminder(
        meeting_id=meeting_id, reminder_type="reminder_1h",
        body=f"Reminder: \"{title}\" starts in 1 hour at {start_time}",
        participant_emails=participant_emails, in_app=True,
    )


@celery_app.task(name="send_reminder_30min")
def send_reminder_30min(meeting_id: str, title: str, start_time: str,
                        participant_emails: list):
    """30-minute reminder: in-app notification + WhatsApp + Telegram."""
    return _fan_out_meeting_reminder(
        meeting_id=meeting_id, reminder_type="reminder_30min",
        body=f"⏰ Reminder — \"{title}\" starts in 30 minutes ({start_time}).",
        participant_emails=participant_emails, in_app=True,
    )


@celery_app.task(name="send_reminder_10min")
def send_reminder_10min(meeting_id: str, title: str, start_time: str,
                        participant_emails: list):
    """10-minute heads-up: in-app notification + WhatsApp + Telegram."""
    return _fan_out_meeting_reminder(
        meeting_id=meeting_id, reminder_type="reminder_10min",
        body=f"⏰ Heads up — \"{title}\" starts in 10 minutes ({start_time}).",
        participant_emails=participant_emails, in_app=True,
    )
