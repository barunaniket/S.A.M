"""
whatsapp_orchestrator.py
------------------------
Single entry point for inbound WhatsApp activity.

Resolves the phone number to a faculty user, branches on document vs text,
runs file ingestion when needed, calls the LLM for natural-language intent,
and dispatches to the intent router.
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from src.api.routes.uploads import persist_pending_upload
from src.services.conversation_store import (
    already_seen,
    append_history,
    clear_session,
    get_session,
    set_session,
)
from src.services.file_ingestor import (
    SUPPORTED_EXTS,
    extract_attendees,
    extract_meeting_metadata,
    parse_file,
    summarize,
    summarize_meeting,
)
from src.services.intent_router import route_intent
from src.services.llm_processor import LLMProcessor
from src.services.memory_store import append_log as memory_append_log
from src.services.whatsapp_audit import log_inbound
from src.services.whatsapp_queue import queue_whatsapp
from src.services.whatsapp_service import download_media, send_buttons
from src.utils.config_loader import Config
from src.utils.db_handler import get_db_connection, release_db_connection


# Button IDs used in interactive replies. The LLM never sees these — they're
# routed straight to the action layer.
BTN_CONFIRM_UPLOAD    = "sam_confirm_upload"
BTN_DISCARD_UPLOAD    = "sam_discard_upload"
BTN_CONFIRM_TIMETABLE = "sam_confirm_timetable"
BTN_DISCARD_TIMETABLE = "sam_discard_timetable"
BTN_CONFIRM_TASKS     = "sam_confirm_tasks"
BTN_DISCARD_TASKS     = "sam_discard_tasks"
# Meeting scheduler card (Path 1 + Path 2 share these)
BTN_MEETING_ONLINE    = "sam_meeting_online"
BTN_MEETING_OFFLINE   = "sam_meeting_offline"
BTN_MEETING_CONFIRM   = "sam_meeting_confirm"
BTN_MEETING_EDIT      = "sam_meeting_edit"
BTN_MEETING_DISCARD   = "sam_meeting_discard"

logger = logging.getLogger(__name__)


_MIME_EXT = {
    # Documents
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    # Images (Tesseract OCR)
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    # Audio (faster-whisper). WhatsApp voice notes arrive as audio/ogg
    # (Opus). audio/mp4 covers iOS .m4a recordings.
    "audio/ogg": ".ogg",
    "audio/oga": ".oga",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/aac": ".aac",
    "audio/amr": ".amr",
}


# ---------------------------------------------------------------------------
# User resolution
# ---------------------------------------------------------------------------

def _normalize_phone(phone: str) -> str:
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def resolve_user_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    """Look up a faculty/admin user by phone_number. Returns None if not found."""
    digits = _normalize_phone(phone)
    if not digits:
        return None

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # Match either with or without leading country code by suffix match.
        cur.execute(
            """
            SELECT id, org_id, email, full_name, role, phone_number,
                   batch, department, office_location, telegram_chat_id
              FROM users
             WHERE regexp_replace(phone_number, '[^0-9]', '', 'g') = %s
                OR regexp_replace(phone_number, '[^0-9]', '', 'g') LIKE %s
             LIMIT 1;
            """,
            (digits, f"%{digits[-10:]}"),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        release_db_connection(conn)


# ---------------------------------------------------------------------------
# Reply helper
# ---------------------------------------------------------------------------

def _reply(phone: str, body: str, role: str = "assistant",
           org_id: int = None, user_id: int = None) -> None:
    meta = {"channel": "orchestrator"}
    if org_id is not None:
        meta["org_id"] = org_id
    if user_id is not None:
        meta["user_id"] = user_id
    queue_whatsapp(phone, body, metadata=meta)
    append_history(phone, role, body)
    # Persistent log alongside the Redis hot cache.
    memory_append_log(user_id, role, body, org_id=org_id, phone=phone,
                      channel="whatsapp", metadata={"source": "orchestrator"})


def _send_confirm_buttons(phone: str, user: Dict[str, Any], summary: str,
                          meeting_found: bool = False) -> None:
    """
    Outbound interactive prompt for confirm/discard of a pending upload.

    The button label adapts: "Schedule" when the file contained a real
    meeting, "Send to all" when it didn't.
    """
    if meeting_found:
        prompt_tail = (
            "I'll schedule this meeting and notify everyone (email + WhatsApp) "
            "with a calendar attachment, plus 24h and 1h reminders. "
            "Tap **Schedule** to go ahead, or reply with edits."
        )
        confirm_label = "Schedule"
    else:
        prompt_tail = (
            "I have the contact list but no meeting details yet — when and "
            "where is the meeting? Or reply with the message you want sent "
            "without scheduling anything."
        )
        confirm_label = "Send anyway"

    body = f"{summary}\n\n{prompt_tail}"
    try:
        result = send_buttons(
            to_phone=phone,
            body=body,
            buttons=[
                {"id": BTN_CONFIRM_UPLOAD, "title": confirm_label},
                {"id": BTN_DISCARD_UPLOAD, "title": "Discard"},
            ],
            footer="S.A.M.",
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error"))
        append_history(phone, "assistant", body, extra={"interactive": True})
    except Exception as e:
        # Fall back to plain text if interactive send fails (e.g. sandbox).
        logger.warning("send_buttons failed, falling back to text: %s", e)
        _reply(phone, body, org_id=user.get("org_id"), user_id=user.get("id"))


# ---------------------------------------------------------------------------
# Inbound handling
# ---------------------------------------------------------------------------

def _ext_from_mime(mime: str, filename: str = "") -> str:
    if filename:
        sfx = Path(filename).suffix.lower()
        if sfx in SUPPORTED_EXTS:
            return sfx
    return _MIME_EXT.get((mime or "").split(";")[0].strip(), "")


def _save_media_for_user(user: Dict[str, Any], data: bytes, ext: str) -> Path:
    org_id = user["org_id"]
    dest_dir = Path(Config.UPLOAD_DIR) / str(org_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4().hex}{ext}"
    dest.write_bytes(data)
    return dest


def _handle_document(user: Dict[str, Any], phone: str, msg: Dict[str, Any]) -> None:
    doc = msg.get("document") or msg.get("image") or msg.get("audio") or msg.get("video")
    if not doc:
        _reply(phone, "I couldn't read that attachment.")
        return

    media_id = doc.get("id")
    filename = doc.get("filename", "")
    mime     = doc.get("mime_type", "")

    ext = _ext_from_mime(mime, filename)
    if ext not in SUPPORTED_EXTS:
        _reply(
            phone,
            "Sorry — I couldn't recognise that attachment. I can read Excel, PDF, "
            "Word, plain text, photos (JPG/PNG/WEBP), and voice notes "
            "(OGG/MP3/M4A/WAV).",
        )
        return

    try:
        binary, _ = download_media(media_id)
    except Exception as e:
        logger.exception("download_media failed")
        _reply(phone, f"I couldn't download that file: {e}")
        return

    saved = _save_media_for_user(user, binary, ext)
    try:
        parsed = parse_file(str(saved))
    except Exception as e:
        try:
            os.remove(saved)
        except OSError:
            pass
        _reply(phone, f"I couldn't parse the file: {e}")
        return

    # Branch: the user asked to onboard their timetable, so anything they
    # send next is the timetable itself (image/audio/text).
    session = get_session(phone) or {}
    if session.get("state") == "AWAITING_TIMETABLE":
        _handle_timetable_upload(user, phone, parsed, saved)
        return

    # Branch: bulk task-assignment flow. Any media uploaded after the admin
    # said "assign tasks" gets routed to the task extractor.
    if session.get("state") == "AWAITING_TASKS":
        _handle_tasks_upload(user, phone, parsed, saved)
        return

    attendees = extract_attendees(parsed)
    meeting   = extract_meeting_metadata(parsed)
    summary   = summarize(parsed, attendees)

    # Demo path 1: a clearly-detected meeting in the file → stage as a
    # meeting draft and ask online/offline. We bypass the legacy upload-
    # confirm broadcast path because the new card is the better UX.
    if meeting and meeting.get("found"):
        participants = []
        for a in attendees or []:
            n = a.get("name") or a.get("email") or a.get("phone")
            if n:
                participants.append(n)
        draft = {
            "title":      meeting.get("title"),
            "start_time": meeting.get("start_time"),
            "end_time":   meeting.get("end_time"),
            "location":   meeting.get("location"),
            "agenda":     meeting.get("agenda"),
            "participants": participants,
            "mode": None,
        }
        # Ack to the user so the chat reflects the extraction.
        _reply(phone,
               f"I see you want to schedule a meeting — extracted these details:\n\n"
               f"{_meeting_summary_text(draft)}",
               org_id=user.get("org_id"), user_id=user.get("id"))
        _stage_meeting_draft(phone, user, draft)
        return

    meeting_summary = summarize_meeting(meeting)
    if meeting_summary:
        summary = f"{summary}\n\nMeeting found in the file:\n{meeting_summary}"

    upload_id = persist_pending_upload(
        org_id=user["org_id"],
        user_id=user["id"],
        file_path=str(saved),
        parsed={**parsed, "attendees": attendees, "meeting": meeting},
    )

    session.update({
        "user_id":            user["id"],
        "org_id":             user["org_id"],
        "state":              "AWAITING_INTENT",
        "pending_upload_id":  upload_id,
        "pending_attendees":  attendees,
        "pending_meeting":    meeting,
    })
    set_session(phone, session)

    _send_confirm_buttons(
        phone, user, f"Got it. {summary}",
        meeting_found=bool(meeting and meeting.get("found")),
    )


# ---------------------------------------------------------------------------
# Timetable onboarding (M2)
# ---------------------------------------------------------------------------

def _handle_timetable_upload(user: Dict[str, Any], phone: str,
                             parsed: Dict[str, Any], saved_path: Any) -> None:
    """
    Faculty sent a timetable (image OCR / voice transcript / text) and we're
    in AWAITING_TIMETABLE state. Run timetable_extractor on the parsed text,
    persist as a pending_upload, and echo the grid back with confirm/discard.
    """
    from src.services.timetable_extractor import (
        extract_timetable,
        summarize_timetable,
    )

    text = parsed.get("text") or ""
    if not text.strip():
        _reply(phone,
               "I couldn't read any text from that. Please try a clearer photo "
               "or send the timetable as text.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    extraction = extract_timetable(text)
    entries = extraction.get("entries", [])

    if not entries:
        _reply(phone,
               "I couldn't pick out any classes from that. Could you re-send "
               "with clearer day/time labels, or type the timetable out?",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # Persist as a pending_upload with parse_kind='timetable' so the UI can
    # render it for editing too (web review path).
    upload_id = persist_pending_upload(
        org_id=user["org_id"],
        user_id=user["id"],
        file_path=str(saved_path),
        parsed={**parsed, "timetable": entries,
                "needs_review": extraction.get("needs_review", False)},
        parse_kind="timetable",
    )

    session = get_session(phone) or {}
    session.update({
        "user_id":              user["id"],
        "org_id":               user["org_id"],
        "state":                "AWAITING_TIMETABLE_CONFIRM",
        "pending_upload_id":    upload_id,
        "pending_timetable":    entries,
    })
    set_session(phone, session)

    note = ""
    if extraction.get("needs_review"):
        note = ("\n\n_(Some cells looked ambiguous — please double-check "
                "before confirming.)_")

    body = (f"Here's the timetable I extracted:\n\n"
            f"{summarize_timetable(entries)}{note}\n\n"
            "Tap *Save* to store it, or *Discard* and re-send.")

    try:
        result = send_buttons(
            to_phone=phone,
            body=body,
            buttons=[
                {"id": "sam_confirm_timetable", "title": "Save"},
                {"id": "sam_discard_timetable", "title": "Discard"},
            ],
            footer="S.A.M. timetable",
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error"))
        append_history(phone, "assistant", body, extra={"interactive": True})
    except Exception:
        _reply(phone, body, org_id=user.get("org_id"), user_id=user.get("id"))


# ---------------------------------------------------------------------------
# Bulk task assignment (M4)
# ---------------------------------------------------------------------------

def _handle_tasks_upload(user: Dict[str, Any], phone: str,
                         parsed: Dict[str, Any], saved_path: Any) -> None:
    """
    Admin sent a file/photo/audio after declaring "I want to assign tasks".
    Run task_extractor and echo the parsed list back with confirm/discard.
    """
    from src.services.task_extractor import extract_tasks, summarize_tasks

    text = parsed.get("text") or ""
    if not text.strip():
        _reply(phone,
               "I couldn't read any text from that. Send a clearer photo, a "
               "voice note, or paste the assignments as text.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    extraction = extract_tasks(text)
    tasks = extraction.get("tasks", [])
    if not tasks:
        _reply(phone,
               "I couldn't pick out any task assignments from that. Try "
               "phrases like 'Prof Sharma will do X by Friday'.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    upload_id = persist_pending_upload(
        org_id=user["org_id"],
        user_id=user["id"],
        file_path=str(saved_path),
        parsed={**parsed, "tasks": tasks},
        parse_kind="tasks",
    )

    session = get_session(phone) or {}
    session.update({
        "user_id":           user["id"],
        "org_id":            user["org_id"],
        "state":             "AWAITING_TASKS_CONFIRM",
        "pending_upload_id": upload_id,
        "pending_tasks":     tasks,
    })
    set_session(phone, session)

    note = ""
    if extraction.get("needs_review"):
        note = "\n\n_(Some entries looked ambiguous — review carefully.)_"

    body = (f"Here are the tasks I extracted ({len(tasks)} total):\n\n"
            f"{summarize_tasks(tasks)}{note}\n\n"
            "Tap *Send out* to assign + schedule reminders, or *Discard*.")

    # Long lists go via web link in the third button.
    review_button = None
    if len(tasks) > 6:
        review_button = {
            "id": f"sam_review_tasks_{upload_id}",
            "title": "Review",
        }

    buttons = [
        {"id": BTN_CONFIRM_TASKS, "title": "Send out"},
        {"id": BTN_DISCARD_TASKS, "title": "Discard"},
    ]
    if review_button:
        buttons.append(review_button)

    try:
        result = send_buttons(
            to_phone=phone,
            body=body,
            buttons=buttons,
            footer="S.A.M. tasks",
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error"))
        append_history(phone, "assistant", body, extra={"interactive": True})
    except Exception:
        # Fallback to plain text if WhatsApp interactive fails.
        _reply(phone, body + "\n\nReply *send* to send or *discard*.",
               org_id=user.get("org_id"), user_id=user.get("id"))


def _send_pending_tasks(user: Dict[str, Any], phone: str,
                        session: Dict[str, Any]) -> Dict[str, Any]:
    """Persist + dispatch the tasks currently in session."""
    from src.services.task_service import create_tasks_bulk, format_task_message
    from src.utils.db_handler import get_user_by_email

    tasks = session.get("pending_tasks") or []
    if not tasks:
        return {"success": False, "message": "No tasks to send."}

    created = create_tasks_bulk(
        org_id=user["org_id"], assigned_by=user["id"],
        tasks=tasks,
        source_upload_id=session.get("pending_upload_id"),
        schedule_reminders=True,
    )

    # Mark pending_upload executed.
    upload_id = session.get("pending_upload_id")
    if upload_id:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SET LOCAL app.org_id = %s;", (str(user["org_id"]),))
            cur.execute(
                "UPDATE pending_uploads SET status='EXECUTED' WHERE id = %s;",
                (upload_id,),
            )
            conn.commit()
            cur.close()
        finally:
            release_db_connection(conn)

    # Send each assignee a personalised kickoff DM (best-effort).
    sent = unmatched = 0
    for c in created:
        body = format_task_message(c, kind="assigned")
        target_phone = None
        if c.get("assignee_id") and c.get("assignee_email"):
            try:
                u = get_user_by_email(c["assignee_email"])
                if u:
                    target_phone = u.get("phone_number")
            except Exception:
                pass
        if target_phone:
            try:
                queue_whatsapp(target_phone, body, metadata={
                    "channel": "task_assignment",
                    "task_id": c["id"],
                    "org_id":  user["org_id"],
                    "user_id": c.get("assignee_id"),
                })
                sent += 1
            except Exception:
                logger.exception("Failed to queue task DM for %s", target_phone)
        else:
            unmatched += 1

    msg_parts = [f"Sent out {len(created)} task(s)."]
    if sent:
        msg_parts.append(f"Notified {sent} on WhatsApp.")
    if unmatched:
        msg_parts.append(f"{unmatched} couldn't be reached on WhatsApp "
                         "(missing phone or unmatched name).")
    return {"success": True, "message": " ".join(msg_parts)}


def _save_pending_timetable(user: Dict[str, Any], phone: str,
                            session: Dict[str, Any]) -> Dict[str, Any]:
    """Persist the entries currently in session into timetable_entries."""
    from src.services.timetable_service import upsert_entries

    entries = session.get("pending_timetable") or []
    if not entries:
        return {"success": False, "message": "No timetable to save."}
    rows = upsert_entries(
        org_id=user["org_id"],
        user_id=user["id"],
        entries=entries,
        source=session.get("pending_timetable_source", "whatsapp"),
        replace_all=True,
    )
    # Mark the pending upload as executed.
    upload_id = session.get("pending_upload_id")
    if upload_id:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SET LOCAL app.org_id = %s;", (str(user["org_id"]),))
            cur.execute(
                "UPDATE pending_uploads SET status = 'EXECUTED' WHERE id = %s;",
                (upload_id,),
            )
            conn.commit()
            cur.close()
        finally:
            release_db_connection(conn)

    return {"success": True,
            "message": f"Saved {rows} class(es). Students can now ask me where you are."}


# ---------------------------------------------------------------------------
# Meeting scheduler card (Path 1 + Path 2)
# ---------------------------------------------------------------------------

def _meeting_summary_text(draft: Dict[str, Any]) -> str:
    """Compact text summary used inside both the mode-pick and confirm cards."""
    title    = draft.get("title")    or "Untitled meeting"
    start    = draft.get("start_time") or "(time TBD)"
    end      = draft.get("end_time")
    location = draft.get("location")
    agenda   = draft.get("agenda")
    parts    = draft.get("participants") or []

    when = start
    if start and end:
        when = f"{start} → {end}"

    lines = [f"📅 *{title}*", f"🕒 {when}"]
    if location:
        lines.append(f"📍 {location}")
    if parts:
        if len(parts) <= 4:
            lines.append("👥 " + ", ".join(parts))
        else:
            lines.append(f"👥 {', '.join(parts[:4])} (+{len(parts)-4} more)")
    if agenda:
        lines.append(f"📝 {agenda}")
    return "\n".join(lines)


def _send_meeting_mode_buttons(phone: str, user: Dict[str, Any],
                               draft: Dict[str, Any]) -> None:
    """After extraction, ask Online vs Offline."""
    body = (f"{_meeting_summary_text(draft)}\n\n"
            "Should this be *online* or *offline*?")
    try:
        result = send_buttons(
            to_phone=phone,
            body=body,
            buttons=[
                {"id": BTN_MEETING_ONLINE,  "title": "Online"},
                {"id": BTN_MEETING_OFFLINE, "title": "Offline"},
                {"id": BTN_MEETING_DISCARD, "title": "Discard"},
            ],
            footer="S.A.M.",
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error"))
        append_history(phone, "assistant", body, extra={"interactive": True})
    except Exception:
        _reply(phone, body + "\n\nReply *online* or *offline*.",
               org_id=user.get("org_id"), user_id=user.get("id"))


def _send_meeting_confirm_card(phone: str, user: Dict[str, Any],
                               draft: Dict[str, Any]) -> None:
    """After Online/Offline pick, show the full card with Confirm/Edit/Discard."""
    mode = (draft.get("mode") or "").lower()
    extra = ""
    if mode == "online":
        extra = "🔗 _Google Meet link will be created on confirm._"
    elif mode == "offline":
        room = draft.get("location") or "TBD"
        extra = (f"🚪 Offline — room *{room}*.\n"
                 "_I'll notify the booking authority for confirmation._")

    body = f"{_meeting_summary_text(draft)}\n\n{extra}\n\nLooks correct?"
    try:
        result = send_buttons(
            to_phone=phone,
            body=body,
            buttons=[
                {"id": BTN_MEETING_CONFIRM, "title": "Yes, schedule"},
                {"id": BTN_MEETING_EDIT,    "title": "Edit"},
                {"id": BTN_MEETING_DISCARD, "title": "Discard"},
            ],
            footer="S.A.M.",
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error"))
        append_history(phone, "assistant", body, extra={"interactive": True})
    except Exception:
        _reply(phone,
               body + "\n\nReply *yes* to schedule, *edit* to change a field, "
               "or *discard*.",
               org_id=user.get("org_id"), user_id=user.get("id"))


def _stage_meeting_draft(phone: str, user: Dict[str, Any],
                         draft: Dict[str, Any]) -> None:
    """Persist a parsed meeting draft into the session and ask online/offline."""
    session = get_session(phone) or {}
    session.update({
        "user_id": user["id"],
        "org_id":  user["org_id"],
        "state":   "AWAITING_MEETING_MODE",
        "pending_meeting_draft": draft,
    })
    set_session(phone, session)
    _send_meeting_mode_buttons(phone, user, draft)


def _execute_pending_meeting(user: Dict[str, Any], phone: str,
                             session: Dict[str, Any]) -> Dict[str, Any]:
    """User tapped Confirm. Create the calendar event, surface meet link or
    trigger booking flow, return the message body for the orchestrator reply."""
    from datetime import datetime as _dt
    from src.services.meeting_creator import create_meeting

    draft = session.get("pending_meeting_draft") or {}
    if not draft.get("start_time"):
        return {"success": False,
                "message": "I don't have a start time for that meeting yet."}

    mode = (draft.get("mode") or "online").lower()
    result = create_meeting(
        title=draft.get("title") or "Meeting",
        start_datetime=draft["start_time"],
        end_datetime=draft.get("end_time") or draft["start_time"],
        participant_names=draft.get("participants") or [],
        scheduler_email=user.get("email"),
        org_id=user.get("org_id"),
        mode=mode,
    )

    if not result.get("success"):
        return result

    msg_lines = ["✅ Meeting scheduled."]
    if result.get("meeting_id"):
        msg_lines.append(f"Calendar event ID: `{result['meeting_id']}`")
    if mode == "online" and result.get("meet_link"):
        msg_lines.append(f"🔗 Meet link: {result['meet_link']}")
    if mode == "offline" and draft.get("location"):
        # Trigger booking authority approval.
        try:
            from src.services.booking_service import request_booking
            starts = _dt.fromisoformat(str(draft["start_time"]).replace("Z", ""))
            ends_iso = draft.get("end_time") or draft["start_time"]
            ends = _dt.fromisoformat(str(ends_iso).replace("Z", ""))
            request_booking(
                org_id=user["org_id"], requested_by=user["id"],
                room_label=draft["location"], starts_at=starts,
                ends_at=ends, purpose=draft.get("title"),
                meeting_id=result.get("meeting_id"),
                requester_name=user.get("full_name"),
            )
            msg_lines.append(f"🚪 Booking authority notified for *{draft['location']}*.")
        except Exception:
            logger.exception("request_booking failed for meeting %s", result.get("meeting_id"))
            msg_lines.append(
                f"⚠️ Couldn't reach the booking authority for {draft['location']} — "
                "you may want to confirm the room manually.")

    msg_lines.append("Invites sent. I'll remind everyone 30 min before.")
    return {"success": True, "data": result, "message": "\n".join(msg_lines)}


def _execute_pending_upload(user: Dict[str, Any], phone: str,
                            session: Dict[str, Any], entities: Dict[str, Any]) -> Dict[str, Any]:
    """
    User confirmed the pending upload. Build a broadcast action using either
    the body the LLM extracted, or the parsed file text as fallback.
    """
    upload_id = entities.get("pending_upload_id") or session.get("pending_upload_id")
    if not upload_id:
        return {"success": False, "message": "No pending upload to confirm."}

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SET LOCAL app.org_id = %s;", (str(user["org_id"]),))
        cur.execute(
            "SELECT parsed FROM pending_uploads WHERE id = %s AND status = 'PARSED';",
            (upload_id,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return {"success": False, "message": "That upload is no longer pending."}

        parsed_field = row["parsed"]
        if isinstance(parsed_field, str):
            try:
                parsed = json.loads(parsed_field)
            except json.JSONDecodeError:
                parsed = {}
        else:
            parsed = parsed_field or {}

        cur.execute(
            "UPDATE pending_uploads SET status = 'EXECUTED' WHERE id = %s;",
            (upload_id,),
        )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    attendees   = parsed.get("attendees") or session.get("pending_attendees") or []
    file_meeting = parsed.get("meeting") or session.get("pending_meeting") or {}

    # Merge meeting fields. The teacher's chat reply (entities) wins over the
    # file's extracted metadata — they may be correcting/overriding it.
    merged_title    = entities.get("title")    or file_meeting.get("title")
    merged_start    = entities.get("start_time") or file_meeting.get("start_time")
    merged_end      = entities.get("end_time")   or file_meeting.get("end_time")
    merged_location = entities.get("location")   or file_meeting.get("location")
    merged_agenda   = entities.get("agenda")     or file_meeting.get("agenda")

    body  = entities.get("body") or parsed.get("text") or ""
    title = merged_title or "Update from your faculty"

    # If we have a meeting time (from file OR teacher), schedule a lightweight
    # meeting: persist + ICS + email/WhatsApp invites + 24h/1h reminders.
    if merged_start and attendees:
        from src.services.meeting_lite import create_meeting_lite

        return create_meeting_lite(
            org_id=user["org_id"],
            organizer_id=user["id"],
            organizer_name=user.get("full_name"),
            organizer_email=user.get("email"),
            title=title,
            start_time=merged_start,
            end_time=merged_end,
            attendees=attendees,
            location=merged_location,
            agenda=merged_agenda or body or None,
            upload_id=upload_id,
        )

    # Otherwise: fall back to the existing one-shot broadcast (no calendar,
    # no reminders) — preserves the old behaviour for "just notify them" cases.
    from src.services.broadcast_service import broadcast_to_attendees
    return broadcast_to_attendees(
        attendees=attendees,
        subject=title,
        body=body,
        channels=entities.get("channels") or ["email", "whatsapp"],
    )


def _handle_text(user: Dict[str, Any], phone: str, text: str) -> None:
    session = get_session(phone) or {}
    session.update({"user_id": user["id"], "org_id": user["org_id"]})
    append_history(phone, "user", text)
    memory_append_log(user["id"], "user", text,
                      org_id=user.get("org_id"), phone=phone,
                      channel="whatsapp")

    context = {
        "speaker_email":      user.get("email"),
        "speaker_full_name":  user.get("full_name"),
        "channel":            "whatsapp",
        "state":              session.get("state"),
        "pending_upload_id":  session.get("pending_upload_id"),
        "history":            session.get("history", [])[-6:],
    }

    parsed_intent = LLMProcessor().process_user_intent(
        text, context, user_id=user["id"]
    )
    intent = parsed_intent.get("intent")

    # Map confirm/discard intents directly when there's a pending upload.
    if intent == "discard_upload":
        _discard_pending(user, phone, session)
        _reply(phone, "Okay, I've discarded the upload.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if intent == "confirm_upload":
        result = _execute_pending_upload(user, phone, session, parsed_intent.get("entities", {}))
        clear_session(phone)
        msg = result.get("message") or (
            "Done — message sent to everyone." if result.get("success")
            else "Couldn't complete that. " + (result.get("error") or "")
        )
        _reply(phone, msg, org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # ----- Timetable onboarding (M2) -----
    if intent == "onboard_timetable":
        if user.get("role") not in ("ADMIN", "FACULTY", "SUPER_ADMIN"):
            _reply(phone,
                   "Only faculty/admin can publish a timetable.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        session.update({
            "user_id":  user["id"],
            "org_id":   user["org_id"],
            "state":    "AWAITING_TIMETABLE",
        })
        set_session(phone, session)
        _reply(phone,
               "Great — send me your weekly timetable now. You can:\n"
               "• Send a *photo* of your printed timetable\n"
               "• Send a *voice note* describing it\n"
               "• Or *type it out* (one class per line: day, time, subject, room)\n\n"
               "I'll parse it and ask you to confirm before saving.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if intent == "discard_timetable":
        if session.get("state") in ("AWAITING_TIMETABLE", "AWAITING_TIMETABLE_CONFIRM"):
            _discard_pending(user, phone, session)
        clear_session(phone)
        _reply(phone, "Okay, I've discarded that timetable.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if intent == "confirm_timetable":
        result = _save_pending_timetable(user, phone, session)
        clear_session(phone)
        _reply(phone,
               result.get("message") or ("Saved." if result.get("success") else "Couldn't save."),
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # ----- Bulk task assignment (M4) -----
    if intent == "assign_tasks":
        if user.get("role") not in ("ADMIN", "SUPER_ADMIN"):
            _reply(phone,
                   "Only admins can assign tasks in bulk.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        session.update({
            "user_id":  user["id"],
            "org_id":   user["org_id"],
            "state":    "AWAITING_TASKS",
        })
        set_session(phone, session)
        _reply(phone,
               "Got it — send me the assignments now. You can:\n"
               "• Upload a *spreadsheet*, *PDF* or *Word* file with the task list\n"
               "• Send a *photo* of a printed sheet\n"
               "• Send a *voice note* describing the tasks\n"
               "• Or *type* them out\n\n"
               "I'll parse them and ask you to confirm before I notify everyone.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if intent == "discard_tasks":
        if session.get("state") in ("AWAITING_TASKS", "AWAITING_TASKS_CONFIRM"):
            _discard_pending(user, phone, session)
        clear_session(phone)
        _reply(phone, "Okay, I've discarded those tasks.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if intent == "confirm_tasks":
        result = _send_pending_tasks(user, phone, session)
        clear_session(phone)
        _reply(phone,
               result.get("message") or ("Done." if result.get("success") else "Failed."),
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # If admin is in AWAITING_TASKS and typed the assignments inline,
    # parse the text as the task source.
    if session.get("state") == "AWAITING_TASKS":
        from src.services.task_extractor import extract_tasks, summarize_tasks
        extraction = extract_tasks(text)
        tasks = extraction.get("tasks", [])
        if not tasks:
            _reply(phone,
                   "I couldn't pick out any tasks from that. Try one per line, "
                   "e.g. 'Prof Sharma: prepare DSA slides by Friday'.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        upload_id = persist_pending_upload(
            org_id=user["org_id"],
            user_id=user["id"],
            file_path=f"<typed-text:{user['id']}>",
            parsed={"kind": "text", "text": text, "tasks": tasks},
            parse_kind="tasks",
        )
        session.update({
            "state":             "AWAITING_TASKS_CONFIRM",
            "pending_upload_id": upload_id,
            "pending_tasks":     tasks,
        })
        set_session(phone, session)
        _reply(phone,
               f"Here's what I got ({len(tasks)} task(s)):\n\n"
               f"{summarize_tasks(tasks)}\n\n"
               "Reply *send* to dispatch or *discard* to cancel.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # If the user typed their timetable as plain text while we were awaiting
    # one, treat that text as the timetable source.
    if session.get("state") == "AWAITING_TIMETABLE":
        from src.services.timetable_extractor import (
            extract_timetable, summarize_timetable,
        )
        extraction = extract_timetable(text)
        entries = extraction.get("entries", [])
        if not entries:
            _reply(phone,
                   "I couldn't pick out any classes from that. Try again with one "
                   "class per line, e.g. 'Mon 09:00-10:00 DSA Room 204'.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        upload_id = persist_pending_upload(
            org_id=user["org_id"],
            user_id=user["id"],
            file_path=f"<typed-text:{user['id']}>",
            parsed={"kind": "text", "text": text, "timetable": entries},
            parse_kind="timetable",
        )
        session.update({
            "state":             "AWAITING_TIMETABLE_CONFIRM",
            "pending_upload_id": upload_id,
            "pending_timetable": entries,
        })
        set_session(phone, session)
        body = (f"Here's what I got:\n\n{summarize_timetable(entries)}\n\n"
                "Reply *save* to confirm or *discard* to throw it away.")
        _reply(phone, body, org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # NOTE: text-based "yes/ok" affirmation is gone — confirm/discard now
    # lives behind interactive buttons (see _send_confirm_buttons). If a user
    # typed plain "yes" we treat it as a brand-new turn rather than a
    # confirmation, so they can't accidentally fire a broadcast by mistake.

    # If we're awaiting an upload intent and the user typed a free-form
    # message, treat it as the body of the broadcast they want to send.
    if session.get("state") == "AWAITING_INTENT" and intent != "broadcast_notification":
        entities = parsed_intent.get("entities", {}) or {}
        entities.setdefault("body", text)
        result = _execute_pending_upload(user, phone, session, entities)
        clear_session(phone)
        _reply(phone,
               result.get("message") or ("Done." if result.get("success") else "Failed."),
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # ----- Meeting scheduler card (Path 2 / NL + bare intent / edit reply) -----
    if intent == "create_meeting":
        ents = parsed_intent.get("entities", {}) or {}
        # If the user is in the middle of editing a staged draft, fold the
        # newly-extracted fields into the existing draft and re-prompt.
        if session.get("state") == "AWAITING_MEETING_EDIT":
            draft = session.get("pending_meeting_draft") or {}
            for k in ("title", "start_time", "end_time", "location", "agenda"):
                if ents.get(k):
                    draft[k] = ents[k]
            if ents.get("participants"):
                draft["participants"] = ents["participants"]
            if ents.get("mode"):
                draft["mode"] = ents["mode"]
            session["pending_meeting_draft"] = draft
            session["state"] = "AWAITING_MEETING_CONFIRM" if draft.get("mode") \
                               else "AWAITING_MEETING_MODE"
            set_session(phone, session)
            if draft.get("mode"):
                _send_meeting_confirm_card(phone, user, draft)
            else:
                _send_meeting_mode_buttons(phone, user, draft)
            return

        # Bare-intent: faculty said "schedule meeting" with nothing concrete.
        has_anything = any(ents.get(k) for k in
                           ("title", "start_time", "end_time", "location",
                            "agenda", "participants"))
        if not has_anything:
            session["state"] = "AWAITING_MEETING_INPUT"
            set_session(phone, session)
            _reply(phone,
                   "Sure — send me a *photo* of the circular, or just *tell me* "
                   "the details (date, time, location, attendees, agenda).",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        # Stage the draft and ask online/offline.
        draft = {
            "title":      ents.get("title"),
            "start_time": ents.get("start_time"),
            "end_time":   ents.get("end_time"),
            "location":   ents.get("location"),
            "agenda":     ents.get("agenda"),
            "participants": ents.get("participants") or [],
            "mode":       ents.get("mode"),
        }
        # If the LLM already inferred mode from the wording (e.g. "online
        # meeting tomorrow"), skip straight to the confirm card.
        if draft.get("mode") in ("online", "offline"):
            session.update({
                "state": "AWAITING_MEETING_CONFIRM",
                "pending_meeting_draft": draft,
            })
            set_session(phone, session)
            _send_meeting_confirm_card(phone, user, draft)
            return
        _stage_meeting_draft(phone, user, draft)
        return

    # Otherwise, route through the standard intent router.
    result = route_intent(
        parsed_intent,
        scheduler_email=user.get("email"),
        org_id=user.get("org_id"),
    )

    reply_msg = result.get("message") or (
        "Done." if result.get("success") else
        "I had trouble with that — could you rephrase?"
    )
    if result.get("needs_clarification") and parsed_intent.get("message"):
        reply_msg = parsed_intent["message"]

    _reply(phone, reply_msg, org_id=user.get("org_id"), user_id=user.get("id"))


def _discard_pending(user: Dict[str, Any], phone: str, session: Dict[str, Any]) -> None:
    upload_id = session.get("pending_upload_id")
    if not upload_id:
        return
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SET LOCAL app.org_id = %s;", (str(user["org_id"]),))
        cur.execute(
            "UPDATE pending_uploads SET status = 'DISCARDED' WHERE id = %s;",
            (upload_id,),
        )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)
    clear_session(phone)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def _handle_interactive(user: Dict[str, Any], phone: str,
                        message: Dict[str, Any]) -> None:
    """Handle Meta interactive replies (button_reply / list_reply)."""
    interactive = message.get("interactive") or {}
    kind = interactive.get("type")

    if kind == "button_reply":
        reply = interactive.get("button_reply") or {}
        btn_id = reply.get("id")
        log_inbound(phone, "interactive", reply.get("title"),
                    intent=btn_id,
                    org_id=user.get("org_id"), user_id=user.get("id"),
                    metadata={"button_id": btn_id})

        session = get_session(phone) or {}

        if btn_id == BTN_DISCARD_UPLOAD:
            _discard_pending(user, phone, session)
            _reply(phone, "Okay, I've discarded the upload.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        if btn_id == BTN_CONFIRM_UPLOAD:
            # Confirming via button without a fresh body — use whatever the
            # parsed file's text content is (may have been captioned earlier).
            result = _execute_pending_upload(user, phone, session, entities={})
            clear_session(phone)
            _reply(phone,
                   result.get("message") or ("Done." if result.get("success") else "Failed."),
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        if btn_id == BTN_CONFIRM_TIMETABLE:
            result = _save_pending_timetable(user, phone, session)
            clear_session(phone)
            _reply(phone,
                   result.get("message") or ("Saved." if result.get("success") else "Couldn't save."),
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        if btn_id == BTN_DISCARD_TIMETABLE:
            _discard_pending(user, phone, session)
            clear_session(phone)
            _reply(phone, "Okay, I've discarded that timetable.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        if btn_id == BTN_CONFIRM_TASKS:
            result = _send_pending_tasks(user, phone, session)
            clear_session(phone)
            _reply(phone,
                   result.get("message") or ("Done." if result.get("success") else "Failed."),
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        if btn_id == BTN_DISCARD_TASKS:
            _discard_pending(user, phone, session)
            clear_session(phone)
            _reply(phone, "Okay, I've discarded those tasks.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        # ----- Meeting scheduler card -----
        if btn_id in (BTN_MEETING_ONLINE, BTN_MEETING_OFFLINE,
                      BTN_MEETING_CONFIRM, BTN_MEETING_EDIT, BTN_MEETING_DISCARD):
            try:
                if btn_id in (BTN_MEETING_ONLINE, BTN_MEETING_OFFLINE):
                    draft = session.get("pending_meeting_draft") or {}
                    if not draft:
                        _reply(phone,
                               "That card has expired — say *schedule meeting* "
                               "to start again.",
                               org_id=user.get("org_id"), user_id=user.get("id"))
                        return
                    draft["mode"] = "online" if btn_id == BTN_MEETING_ONLINE else "offline"
                    session["pending_meeting_draft"] = draft
                    session["state"] = "AWAITING_MEETING_CONFIRM"
                    set_session(phone, session)
                    _send_meeting_confirm_card(phone, user, draft)
                    return

                if btn_id == BTN_MEETING_CONFIRM:
                    result = _execute_pending_meeting(user, phone, session)
                    clear_session(phone)
                    _reply(phone,
                           result.get("message") or
                           ("Scheduled." if result.get("success")
                            else f"Couldn't schedule: {result.get('error') or 'unknown error'}"),
                           org_id=user.get("org_id"), user_id=user.get("id"))
                    return

                if btn_id == BTN_MEETING_EDIT:
                    session["state"] = "AWAITING_MEETING_EDIT"
                    set_session(phone, session)
                    _reply(phone,
                           "What should I change? Reply with the field — e.g. "
                           "*time 4pm*, *room 305*, *make it online*.",
                           org_id=user.get("org_id"), user_id=user.get("id"))
                    return

                if btn_id == BTN_MEETING_DISCARD:
                    clear_session(phone)
                    _reply(phone, "Okay, dropped that meeting.",
                           org_id=user.get("org_id"), user_id=user.get("id"))
                    return
            except Exception as e:
                logger.exception("Meeting card button %s failed", btn_id)
                _reply(phone,
                       f"⚠️ Something went wrong handling that button: {e}. "
                       "Try saying *schedule meeting* again.",
                       org_id=user.get("org_id"), user_id=user.get("id"))
                return

        # ----- Booking approve/deny (M5) -----
        if btn_id and btn_id.startswith("sam_booking_"):
            from src.services.booking_service import approve_booking, deny_booking
            if user.get("role") not in ("BOOKING_AUTHORITY", "SUPER_ADMIN"):
                _reply(phone,
                       "Only the booking authority can approve/deny bookings.",
                       org_id=user.get("org_id"), user_id=user.get("id"))
                return
            try:
                action, _, raw_id = btn_id[len("sam_booking_"):].partition("_")
                booking_id = int(raw_id)
            except (ValueError, AttributeError):
                _reply(phone, "Couldn't parse that booking action.",
                       org_id=user.get("org_id"), user_id=user.get("id"))
                return
            if action == "approve":
                booking = approve_booking(booking_id, authority_id=user["id"])
                msg = (f"Approved booking #{booking_id}." if booking
                       else f"Booking #{booking_id} not found.")
            elif action == "deny":
                booking = deny_booking(booking_id, authority_id=user["id"])
                msg = (f"Denied booking #{booking_id}." if booking
                       else f"Booking #{booking_id} not found.")
            else:
                msg = "Unknown booking action."
            _reply(phone, msg, org_id=user.get("org_id"), user_id=user.get("id"))
            return

    # Unknown interactive kind — fall back to text-style routing.
    logger.info("Unhandled interactive payload from %s: %s", phone, interactive)


def handle_inbound_message(phone: str, message: Dict[str, Any]) -> None:
    """Process a single Meta `messages[*]` object."""
    msg_id = message.get("id")
    if msg_id and already_seen(msg_id):
        logger.info("Skipping duplicate WhatsApp message %s", msg_id)
        return

    user = resolve_user_by_phone(phone)
    if not user:
        queue_whatsapp(
            phone,
            "Hi! This number isn't registered as a faculty member in S.A.M. "
            "Please contact your admin to get access.",
            metadata={"channel": "system"},
        )
        log_inbound(phone, message.get("type", "text"),
                    body=(message.get("text") or {}).get("body"),
                    metadata={"reason": "unknown_phone"})
        return
    role = user.get("role")
    if role not in ("ADMIN", "FACULTY", "STUDENT", "BOOKING_AUTHORITY", "SUPER_ADMIN"):
        queue_whatsapp(phone, "Your account isn't permitted to drive S.A.M. via WhatsApp.",
                       metadata={"channel": "system"})
        log_inbound(phone, message.get("type", "text"),
                    body=(message.get("text") or {}).get("body"),
                    org_id=user.get("org_id"), user_id=user.get("id"),
                    metadata={"reason": "role_blocked", "role": role})
        return

    msg_type = message.get("type")

    # Students/booking-authority can ask SAM questions but cannot upload
    # documents, photos, or voice notes — those are reserved for the
    # faculty/admin onboarding + bulk-assign flows.
    if msg_type in ("document", "image", "audio", "video") and role not in (
        "ADMIN", "FACULTY", "SUPER_ADMIN"
    ):
        queue_whatsapp(phone,
                       "Sorry — only faculty/admin can upload files or voice notes. "
                       "You can still ask me questions in text.",
                       metadata={"channel": "system"})
        log_inbound(phone, msg_type, body=None,
                    org_id=user.get("org_id"), user_id=user.get("id"),
                    metadata={"reason": "role_blocked_media", "role": role})
        return

    # Audit every inbound turn (best-effort).
    body_for_audit = None
    if msg_type == "text":
        body_for_audit = (message.get("text") or {}).get("body")
    elif msg_type in ("document", "image", "audio", "video"):
        attach = message.get(msg_type) or {}
        body_for_audit = attach.get("filename") or attach.get("caption") or attach.get("mime_type")
    log_inbound(phone, msg_type or "unknown", body_for_audit,
                org_id=user.get("org_id"), user_id=user.get("id"),
                metadata={"message_id": msg_id})

    if msg_type in ("document", "image", "audio", "video"):
        _handle_document(user, phone, message)
        return

    if msg_type == "text":
        text = (message.get("text") or {}).get("body", "").strip()
        if not text:
            return
        _handle_text(user, phone, text)
        return

    if msg_type == "interactive":
        _handle_interactive(user, phone, message)
        return

    logger.info("Ignoring WhatsApp message type=%s", msg_type)


def handle_webhook_payload(payload: Dict[str, Any]) -> None:
    """Walk a Meta webhook payload and dispatch each contained message."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            for message in value.get("messages", []) or []:
                phone = message.get("from")
                if not phone:
                    continue
                try:
                    handle_inbound_message(phone, message)
                except Exception:
                    logger.exception("Failed to handle WhatsApp message from %s", phone)
