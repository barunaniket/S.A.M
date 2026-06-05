"""
telegram_orchestrator.py
------------------------
Single entry point for inbound Telegram activity. Parallel to
whatsapp_orchestrator.py.

Reuses every piece of channel-agnostic logic (intent router, file
ingestor, pending-upload executor, timetable/task save helpers) by
importing it directly from whatsapp_orchestrator. The only Telegram-
specific code here is:

  - update walking + payload normalization
  - chat_id → user resolution (telegram_chat_id column)
  - /start <CODE> pairing flow
  - outbound calls go through queue_telegram + telegram_service.send_buttons
  - session keys live under tg:session:* (not wa:session:*)
"""

import logging
import re
from typing import Any, Dict, Optional

from src.services.conversation_store import (
    already_seen_tg,
    append_history_tg,
    clear_session_tg,
    get_session_tg,
    set_session_tg,
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
from src.services.telegram_queue import queue_telegram
from src.services.telegram_service import (
    answer_callback,
    download_file,
    send_buttons,
    send_text,
)
from src.services.whatsapp_audit import log_inbound
from src.services.whatsapp_orchestrator import (
    BTN_CONFIRM_TASKS,
    BTN_CONFIRM_TIMETABLE,
    BTN_CONFIRM_UPLOAD,
    BTN_DISCARD_TASKS,
    BTN_DISCARD_TIMETABLE,
    BTN_DISCARD_UPLOAD,
    BTN_MEETING_CONFIRM,
    BTN_MEETING_DISCARD,
    BTN_MEETING_EDIT,
    BTN_MEETING_OFFLINE,
    BTN_MEETING_ONLINE,
    _execute_pending_upload,
    _ext_from_mime,
    _meeting_summary_text,
    _save_media_for_user,
    _save_pending_timetable,
    _send_pending_tasks,
)
from src.api.routes.uploads import persist_pending_upload
from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# User resolution + pairing
# ---------------------------------------------------------------------------

def resolve_user_by_chat_id(chat_id: int) -> Optional[Dict[str, Any]]:
    """Look up a user by telegram_chat_id. Returns None if not paired."""
    if not chat_id:
        return None

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, org_id, email, full_name, role, phone_number,
                   telegram_chat_id, telegram_username, batch, department,
                   office_location
              FROM users
             WHERE telegram_chat_id = %s
             LIMIT 1;
            """,
            (int(chat_id),),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        release_db_connection(conn)


_PAIR_RE = re.compile(r"^/start(?:\s+([A-Z0-9]{4,8}))?\s*$", re.IGNORECASE)


def _set_user_batch(user_id: int, batch: str) -> bool:
    """Persist a student's batch selection. Returns True on success."""
    if not batch or len(batch.strip()) > 32:
        return False
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET batch = %s, updated_at = NOW() WHERE id = %s;",
            (batch.strip(), user_id),
        )
        conn.commit()
        cur.close()
        return True
    except Exception:
        conn.rollback()
        logger.exception("Failed to set batch for user %s", user_id)
        return False
    finally:
        release_db_connection(conn)


def _try_consume_pairing_code(code: str, chat_id: int,
                              telegram_username: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Atomically consume a pairing code. Returns the bound user dict on success,
    None if the code is invalid / expired / already used / unknown.
    """
    code = (code or "").strip().upper()
    if not code:
        return None

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # Atomic claim: only one /start can ever consume a given code.
        cur.execute(
            """
            UPDATE telegram_pairing_codes
               SET consumed = TRUE
             WHERE code = %s
               AND consumed = FALSE
               AND expires_at > NOW()
            RETURNING user_id, org_id;
            """,
            (code,),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            cur.close()
            return None

        user_id = row["user_id"]
        org_id  = row["org_id"]

        # Bind the chat_id (and overwrite any previous binding for this user
        # — the pairing flow IS the rebind).
        cur.execute(
            """
            UPDATE users
               SET telegram_chat_id  = %s,
                   telegram_username = %s
             WHERE id = %s
            RETURNING id, org_id, email, full_name, role, phone_number,
                      telegram_chat_id, telegram_username;
            """,
            (int(chat_id), (telegram_username or None), user_id),
        )
        user_row = cur.fetchone()
        conn.commit()
        cur.close()
        return dict(user_row) if user_row else None
    except Exception:
        conn.rollback()
        logger.exception("Pairing code consumption failed")
        return None
    finally:
        release_db_connection(conn)


def _onboarding_message() -> str:
    return (
        "👋 Hi! This Telegram chat isn't linked to a SAM account yet.\n\n"
        "To link it:\n"
        "1. Open the SAM web dashboard\n"
        "2. Go to <b>Settings → Connect Telegram</b>\n"
        "3. Copy the 6-character code shown\n"
        "4. Send <code>/start CODE</code> here\n\n"
        "Once linked, you can chat with me to schedule meetings, run "
        "broadcasts, upload your timetable, and more."
    )


def _start_chat_first_onboarding(chat_id: int,
                                 telegram_username: Optional[str]) -> None:
    """
    Kick off the Google-OAuth-first sign-up flow for an unknown chat.

    Generates an onboarding token, sends the OAuth URL. After the user
    completes Google sign-in, the /auth/callback handler binds the
    chat_id and pushes a welcome DM (handled by services.onboarding).
    """
    try:
        from src.services.onboarding import start_onboarding
        result = start_onboarding(
            channel="telegram",
            identifier=str(chat_id),
            telegram_username=telegram_username,
        )
    except Exception:
        logger.exception("start_onboarding failed for chat %s", chat_id)
        send_text(chat_id,
                  "Sorry — something went wrong starting sign-up. "
                  "Please try /start again in a moment.")
        return

    auth_url = result.get("auth_url")
    send_text(
        chat_id,
        "👋 Welcome to <b>S.A.M</b> — your faculty scheduling assistant.\n\n"
        "First, sign in with your <b>institutional Google account</b> so I can "
        "verify who you are and write to your calendar:\n\n"
        f'<a href="{auth_url}">🔗 Sign in with Google</a>\n\n'
        "<i>The link expires in 15 minutes. Once you're back, I'll know who "
        "you are and we can finish setup here in chat.</i>",
    )


# ---------------------------------------------------------------------------
# Reply helper (mirrors whatsapp_orchestrator._reply)
# ---------------------------------------------------------------------------

def _reply(chat_id: int, body: str, role: str = "assistant",
           org_id: Optional[int] = None, user_id: Optional[int] = None) -> None:
    meta = {"channel": "orchestrator"}
    if org_id is not None:
        meta["org_id"] = org_id
    if user_id is not None:
        meta["user_id"] = user_id
    queue_telegram(chat_id, body, metadata=meta)
    append_history_tg(chat_id, role, body)
    memory_append_log(user_id, role, body, org_id=org_id, phone=str(chat_id),
                      channel="telegram", metadata={"source": "tg_orchestrator"})


def _send_confirm_buttons(chat_id: int, user: Dict[str, Any], summary: str,
                          meeting_found: bool = False) -> None:
    if meeting_found:
        prompt_tail = (
            "I'll schedule this meeting and notify everyone (email + Telegram) "
            "with a calendar attachment, plus 24h and 1h reminders.\n\n"
            "Tap <b>Schedule</b> to go ahead, or reply with edits."
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
            chat_id=chat_id,
            body=body,
            buttons=[
                {"id": BTN_CONFIRM_UPLOAD, "title": confirm_label},
                {"id": BTN_DISCARD_UPLOAD, "title": "Discard"},
            ],
            footer="S.A.M.",
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error"))
        append_history_tg(chat_id, "assistant", body, extra={"interactive": True})
    except Exception as e:
        logger.warning("send_buttons failed, falling back to text: %s", e)
        _reply(chat_id, body, org_id=user.get("org_id"), user_id=user.get("id"))


# ---------------------------------------------------------------------------
# Meeting scheduler card (Telegram mirror of whatsapp_orchestrator helpers)
# ---------------------------------------------------------------------------

def _send_meeting_mode_buttons_tg(chat_id: int, user: Dict[str, Any],
                                  draft: Dict[str, Any]) -> None:
    body = (f"{_meeting_summary_text(draft)}\n\n"
            "Should this be <b>online</b> or <b>offline</b>?")
    try:
        result = send_buttons(
            chat_id=chat_id,
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
        append_history_tg(chat_id, "assistant", body, extra={"interactive": True})
    except Exception:
        _reply(chat_id, body + "\n\nReply <b>online</b> or <b>offline</b>.",
               org_id=user.get("org_id"), user_id=user.get("id"))


def _send_meeting_confirm_card_tg(chat_id: int, user: Dict[str, Any],
                                  draft: Dict[str, Any]) -> None:
    mode = (draft.get("mode") or "").lower()
    extra = ""
    if mode == "online":
        extra = "🔗 <i>Google Meet link will be created on confirm.</i>"
    elif mode == "offline":
        room = draft.get("location") or "TBD"
        extra = (f"🚪 Offline — room <b>{room}</b>.\n"
                 "<i>I'll notify the booking authority for confirmation.</i>")

    body = f"{_meeting_summary_text(draft)}\n\n{extra}\n\nLooks correct?"
    try:
        result = send_buttons(
            chat_id=chat_id,
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
        append_history_tg(chat_id, "assistant", body, extra={"interactive": True})
    except Exception:
        _reply(chat_id,
               body + "\n\nReply <b>yes</b>, <b>edit</b>, or <b>discard</b>.",
               org_id=user.get("org_id"), user_id=user.get("id"))


def _stage_meeting_draft_tg(chat_id: int, user: Dict[str, Any],
                            draft: Dict[str, Any]) -> None:
    session = get_session_tg(chat_id) or {}
    session.update({
        "user_id": user["id"],
        "org_id":  user["org_id"],
        "state":   "AWAITING_MEETING_MODE",
        "pending_meeting_draft": draft,
    })
    set_session_tg(chat_id, session)
    _send_meeting_mode_buttons_tg(chat_id, user, draft)


def _execute_pending_meeting_tg(user: Dict[str, Any], chat_id: int,
                                session: Dict[str, Any]) -> Dict[str, Any]:
    """Telegram twin of whatsapp_orchestrator._execute_pending_meeting."""
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
        msg_lines.append(f"Calendar event ID: <code>{result['meeting_id']}</code>")
    if mode == "online" and result.get("meet_link"):
        msg_lines.append(f"🔗 Meet link: {result['meet_link']}")
    if mode == "offline" and draft.get("location"):
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
            msg_lines.append(f"🚪 Booking authority notified for <b>{draft['location']}</b>.")
        except Exception:
            logger.exception("request_booking failed for meeting %s", result.get("meeting_id"))
            msg_lines.append(
                f"⚠️ Couldn't reach the booking authority for {draft['location']}.")
    msg_lines.append("Invites sent. I'll remind everyone 30 min before.")
    return {"success": True, "data": result, "message": "\n".join(msg_lines)}


# ---------------------------------------------------------------------------
# Document / media handling
# ---------------------------------------------------------------------------

def _extract_telegram_media(message: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Normalize Telegram's various media-bearing message shapes into a single
    {file_id, mime, filename} dict. Returns None if the message has no media.

    Telegram payload variants:
      - document   {file_id, mime_type, file_name, ...}
      - photo      [{file_id, file_size, ...}, ...]   (multiple sizes; pick last)
      - voice      {file_id, mime_type, duration, ...}   (Opus, OGG container)
      - audio      {file_id, mime_type, ...}
      - video      {file_id, mime_type, ...}
    """
    if "document" in message:
        d = message["document"]
        return {
            "file_id":  d.get("file_id"),
            "mime":     d.get("mime_type") or "",
            "filename": d.get("file_name") or "",
        }
    if "photo" in message and message["photo"]:
        # Highest-resolution variant is last in the array.
        p = message["photo"][-1]
        return {"file_id": p.get("file_id"), "mime": "image/jpeg", "filename": ""}
    if "voice" in message:
        v = message["voice"]
        return {"file_id": v.get("file_id"),
                "mime":     v.get("mime_type") or "audio/ogg",
                "filename": ""}
    if "audio" in message:
        a = message["audio"]
        return {"file_id":  a.get("file_id"),
                "mime":     a.get("mime_type") or "audio/mpeg",
                "filename": a.get("file_name") or ""}
    if "video" in message:
        v = message["video"]
        return {"file_id":  v.get("file_id"),
                "mime":     v.get("mime_type") or "video/mp4",
                "filename": v.get("file_name") or ""}
    return None


def _handle_document(user: Dict[str, Any], chat_id: int,
                     message: Dict[str, Any]) -> None:
    media = _extract_telegram_media(message)
    if not media or not media.get("file_id"):
        _reply(chat_id, "I couldn't read that attachment.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    ext = _ext_from_mime(media["mime"], media["filename"])
    if ext not in SUPPORTED_EXTS:
        _reply(
            chat_id,
            "Sorry — I couldn't recognise that attachment. I can read Excel, "
            "PDF, Word, plain text, photos (JPG/PNG/WEBP), and voice notes "
            "(OGG/MP3/M4A/WAV).",
            org_id=user.get("org_id"), user_id=user.get("id"),
        )
        return

    try:
        binary, _ = download_file(media["file_id"])
    except Exception as e:
        logger.exception("Telegram download_file failed")
        _reply(chat_id, f"I couldn't download that file: {e}",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    saved = _save_media_for_user(user, binary, ext)

    # Assignment flows skip OCR — we just store the photo path and link
    # it to the assignment / submission.
    session = get_session_tg(chat_id) or {}
    state_now = session.get("state")
    is_image = ext.lstrip(".").lower() in ("jpg", "jpeg", "png", "webp")

    if state_now == "AWAITING_ASSN_BODY" and is_image:
        from src.services import assignment_service
        payload = session.get("assn_payload") or {}
        result = assignment_service.create(
            org_id=user["org_id"], faculty_id=user["id"],
            batch=payload.get("batch"), subject=payload.get("subject"),
            title=payload.get("title"),
            body_file_path=str(saved),
        )
        clear_session_tg(chat_id)
        _reply(chat_id, result.get("message") or "Created.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if state_now == "AWAITING_ASSN_FILE" and is_image:
        from src.services import assignment_service
        payload = session.get("assn_payload") or {}
        assignment_id = payload.get("assignment_id")
        if not assignment_id:
            _reply(chat_id, "I lost track of which assignment that's for "
                            "— say <i>submit assignment</i> to start over.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            clear_session_tg(chat_id)
            return
        caption = (message.get("caption") or "").strip() or None
        result = assignment_service.register_submission(
            org_id=user["org_id"], assignment_id=int(assignment_id),
            student_id=user["id"], file_path=str(saved),
            caption=caption,
        )
        if not result.get("success"):
            _reply(chat_id, result.get("message") or "Couldn't register that.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        # We keep state AWAITING_ASSN_FILE in case student wants to re-shoot
        # before tapping Yes — but stash the submission id either way.
        payload["pending_submission_id"] = result["submission"]["id"]
        session["assn_payload"] = payload
        set_session_tg(chat_id, session)
        try:
            send_buttons(chat_id=chat_id, body=result["message"],
                         buttons=result["buttons"],
                         footer="Confirm submission")
            append_history_tg(chat_id, "assistant", result["message"],
                              extra={"interactive": True})
        except Exception:
            _reply(chat_id, result["message"] + "\n\nReply <b>yes</b> or <b>no</b>.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
        return

    try:
        parsed = parse_file(str(saved))
    except Exception as e:
        try:
            saved.unlink()
        except Exception:
            pass
        _reply(chat_id, f"I couldn't parse the file: {e}",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if state_now == "AWAITING_TIMETABLE":
        _handle_timetable_upload_tg(user, chat_id, parsed, saved)
        return
    if state_now == "AWAITING_TASKS":
        _handle_tasks_upload_tg(user, chat_id, parsed, saved)
        return

    # ------------------------------------------------------------------
    # Course material upload — caption "material <subject>" or
    # "material <subject> <batch>" stores the file in course_materials.
    # Faculty/admin only. Triggers MCQ generation prompt afterwards.
    # ------------------------------------------------------------------
    caption_raw = (message.get("caption") or "").strip()
    material_match = re.match(
        r"^material\s+([\w\-]+)(?:\s+([\w\-]+))?\s*$",
        caption_raw, flags=re.IGNORECASE,
    ) if caption_raw else None
    if material_match and (user.get("role") or "").upper() in (
        "FACULTY", "ADMIN", "SUPER_ADMIN",
    ):
        subject = material_match.group(1)
        batch = material_match.group(2)
        _handle_material_upload_tg(user, chat_id, parsed, saved,
                                    subject=subject, batch=batch)
        return

    attendees = extract_attendees(parsed)
    meeting   = extract_meeting_metadata(parsed)
    summary   = summarize(parsed, attendees)

    # Demo path 1: a clearly-detected meeting in the file → stage as a
    # meeting draft and ask online/offline.
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
        _reply(chat_id,
               f"I see you want to schedule a meeting — extracted these details:\n\n"
               f"{_meeting_summary_text(draft)}",
               org_id=user.get("org_id"), user_id=user.get("id"))
        _stage_meeting_draft_tg(chat_id, user, draft)
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
    set_session_tg(chat_id, session)

    _send_confirm_buttons(
        chat_id, user, f"Got it. {summary}",
        meeting_found=bool(meeting and meeting.get("found")),
    )


def _handle_timetable_upload_tg(user: Dict[str, Any], chat_id: int,
                                parsed: Dict[str, Any], saved_path: Any) -> None:
    from src.services.timetable_extractor import (
        extract_timetable, summarize_timetable,
    )

    text = parsed.get("text") or ""
    if not text.strip():
        _reply(chat_id,
               "I couldn't read any text from that. Please try a clearer photo "
               "or send the timetable as text.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    extraction = extract_timetable(text)
    entries = extraction.get("entries", [])
    if not entries:
        _reply(chat_id,
               "I couldn't pick out any classes from that. Could you re-send "
               "with clearer day/time labels, or type the timetable out?",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    upload_id = persist_pending_upload(
        org_id=user["org_id"],
        user_id=user["id"],
        file_path=str(saved_path),
        parsed={**parsed, "timetable": entries,
                "needs_review": extraction.get("needs_review", False)},
        parse_kind="timetable",
    )

    session = get_session_tg(chat_id) or {}
    session.update({
        "user_id":              user["id"],
        "org_id":               user["org_id"],
        "state":                "AWAITING_TIMETABLE_CONFIRM",
        "pending_upload_id":    upload_id,
        "pending_timetable":    entries,
        "pending_timetable_source": "telegram",
    })
    set_session_tg(chat_id, session)

    note = ""
    if extraction.get("needs_review"):
        note = ("\n\n<i>(Some cells looked ambiguous — please double-check "
                "before confirming.)</i>")

    body = (f"Here's the timetable I extracted:\n\n"
            f"{summarize_timetable(entries)}{note}\n\n"
            "Tap <b>Save</b> to store it, or <b>Discard</b> and re-send.")

    try:
        result = send_buttons(
            chat_id=chat_id,
            body=body,
            buttons=[
                {"id": BTN_CONFIRM_TIMETABLE, "title": "Save"},
                {"id": BTN_DISCARD_TIMETABLE, "title": "Discard"},
            ],
            footer="S.A.M. timetable",
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error"))
        append_history_tg(chat_id, "assistant", body, extra={"interactive": True})
    except Exception:
        _reply(chat_id, body, org_id=user.get("org_id"), user_id=user.get("id"))


def _handle_material_upload_tg(user: Dict[str, Any], chat_id: int,
                                parsed: Dict[str, Any], saved_path: Any,
                                *, subject: str,
                                batch: Optional[str] = None) -> None:
    """
    Faculty/admin sent a course-material file with caption
    'material <subject> [<batch>]'. Persist to course_materials with the
    extracted text, then offer to generate MCQs from it.
    """
    from src.services import course_materials

    extracted = (parsed.get("text") or "").strip()
    if not extracted or len(extracted) < 100:
        _reply(chat_id,
               "I saved the file, but couldn't extract enough readable text "
               "to generate MCQs from it. Try a clearer scan or a "
               "text-based PDF.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        # Still record so it's findable for human reference.

    title = parsed.get("title") or saved_path.name
    try:
        material = course_materials.record_material(
            org_id=user["org_id"],
            subject=subject,
            batch=batch,
            title=title,
            file_path=str(saved_path),
            mime_type=parsed.get("kind"),
            extracted_text=extracted,
            uploaded_by=user["id"],
        )
    except Exception:
        logger.exception("course_materials insert failed")
        _reply(chat_id, "I couldn't save that material to the library — "
                        "please try again.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    body_lines = [
        f"📚 Saved <b>{title}</b> to the {subject} library "
        f"({len(extracted)} chars indexed).",
    ]
    if extracted:
        body_lines.append(
            "\nWant me to draft attendance MCQs from this? Reply "
            f"<code>generate mcq attendance {subject}</code> or use the "
            "button below."
        )
    body = "\n".join(body_lines)

    if extracted:
        try:
            send_buttons(
                chat_id=chat_id, body=body,
                buttons=[{"id": f"gen_mcq_{material['id']}_{subject}",
                          "title": f"📝 Generate 5 MCQs for {subject}"}],
                footer="Material library",
            )
            return
        except Exception:
            pass

    _reply(chat_id, body,
           org_id=user.get("org_id"), user_id=user.get("id"))


def _handle_tasks_upload_tg(user: Dict[str, Any], chat_id: int,
                            parsed: Dict[str, Any], saved_path: Any) -> None:
    from src.services.task_extractor import extract_tasks, summarize_tasks

    text = parsed.get("text") or ""
    if not text.strip():
        _reply(chat_id,
               "I couldn't read any text from that. Send a clearer photo, a "
               "voice note, or paste the assignments as text.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    extraction = extract_tasks(text)
    tasks = extraction.get("tasks", [])
    if not tasks:
        _reply(chat_id,
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

    session = get_session_tg(chat_id) or {}
    session.update({
        "user_id":           user["id"],
        "org_id":            user["org_id"],
        "state":             "AWAITING_TASKS_CONFIRM",
        "pending_upload_id": upload_id,
        "pending_tasks":     tasks,
    })
    set_session_tg(chat_id, session)

    note = ""
    if extraction.get("needs_review"):
        note = "\n\n<i>(Some entries looked ambiguous — review carefully.)</i>"

    body = (f"Here are the tasks I extracted ({len(tasks)} total):\n\n"
            f"{summarize_tasks(tasks)}{note}\n\n"
            "Tap <b>Send out</b> to assign + schedule reminders, or <b>Discard</b>.")

    try:
        result = send_buttons(
            chat_id=chat_id,
            body=body,
            buttons=[
                {"id": BTN_CONFIRM_TASKS, "title": "Send out"},
                {"id": BTN_DISCARD_TASKS, "title": "Discard"},
            ],
            footer="S.A.M. tasks",
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error"))
        append_history_tg(chat_id, "assistant", body, extra={"interactive": True})
    except Exception:
        _reply(chat_id, body + "\n\nReply <b>send</b> to send or <b>discard</b>.",
               org_id=user.get("org_id"), user_id=user.get("id"))


def _discard_pending_tg(user: Dict[str, Any], chat_id: int,
                        session: Dict[str, Any]) -> None:
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
    clear_session_tg(chat_id)


# ---------------------------------------------------------------------------
# Text handling
# ---------------------------------------------------------------------------

def _handle_text(chat_id: int, text: str,
                 telegram_username: Optional[str] = None,
                 user: Optional[Dict[str, Any]] = None) -> None:
    """
    Handle a plain-text Telegram message. Special-cases /start CODE and /help
    before falling through to the LLM intent path.
    """
    text = (text or "").strip()
    if not text:
        return

    # ---- /start <CODE>: pairing flow ----
    pair = _PAIR_RE.match(text)
    if pair:
        code = (pair.group(1) or "").upper()
        if not code:
            # /start with no code:
            #   - already linked → friendly re-greeting
            #   - unknown chat   → kick off chat-first Google OAuth onboarding
            if user:
                _reply(chat_id,
                       f"You're already linked as <b>{user.get('full_name')}</b>. "
                       "Send me anything to get started — try "
                       "<i>“my agenda today”</i> or <i>“set up my timetable”</i>.",
                       org_id=user.get("org_id"), user_id=user.get("id"))
            else:
                _start_chat_first_onboarding(chat_id, telegram_username)
            return

        bound = _try_consume_pairing_code(code, chat_id, telegram_username)
        if not bound:
            send_text(chat_id,
                      "❌ That code is invalid, expired, or already used. "
                      "Generate a fresh one from "
                      "<b>Settings → Connect Telegram</b> in the SAM web app.")
            return
        send_text(chat_id,
                  f"✅ Linked as <b>{bound.get('full_name')}</b> "
                  f"(<i>{bound.get('role','FACULTY')}</i>). "
                  "You can now chat with me — try <i>“my agenda today”</i> or "
                  "send a photo of your timetable to get started.")
        log_inbound(str(chat_id), "command", text,
                    intent="pair", org_id=bound.get("org_id"),
                    user_id=bound.get("id"),
                    metadata={"chat_id": chat_id, "code": code},
                    channel="telegram")
        return

    # ---- /help ----
    if text.lower().startswith("/help"):
        send_text(chat_id,
                  "I can help you with:\n"
                  "• <b>Schedule meetings</b> — “meet Dr Sharma tomorrow 3pm”\n"
                  "• <b>Daily agenda</b> — “what's on today?”\n"
                  "• <b>Broadcasts</b> — “tell CSE-3A class is cancelled”\n"
                  "• <b>Timetable</b> — send a photo or “set up my timetable”\n"
                  "• <b>Bulk tasks</b> — “assign tasks” + share a sheet/photo\n"
                  "• <b>Bookings</b> — approve or deny pending requests\n\n"
                  "Need to disconnect? Use <i>Settings → Telegram</i> in the web app.")
        return

    # User must be paired beyond this point. Anyone DMing the bot for the
    # first time without a pairing code goes through chat-first onboarding.
    if not user:
        _start_chat_first_onboarding(chat_id, telegram_username)
        log_inbound(str(chat_id), "text", text,
                    metadata={"reason": "unpaired_chat", "chat_id": chat_id},
                    channel="telegram")
        return

    # ---- AWAITING_BATCH: student post-onboarding batch capture ----
    session_for_state = get_session_tg(chat_id) or {}
    if session_for_state.get("state") == "AWAITING_BATCH":
        # Accept short alphanum batch codes only; ignore anything that
        # looks like a sentence so the student can re-prompt.
        candidate = text.strip()
        if 2 <= len(candidate) <= 16 and not any(ch in candidate for ch in (" ", "?", "!")):
            if _set_user_batch(user["id"], candidate):
                clear_session_tg(chat_id)
                _reply(chat_id,
                       f"✅ Saved your batch as <b>{candidate}</b>. You're all set.\n\n"
                       "You can ask me where any teacher will be, see your batch's "
                       "announcements, or get help — try <code>/help</code>.",
                       org_id=user.get("org_id"), user_id=user.get("id"))
                return
        _reply(chat_id,
               "Hmm, that doesn't look like a batch code. Reply with just the "
               "code (e.g. <code>CSE-3A</code>, <code>ECE-2B</code>).",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # ---- Assignment state machine (text inputs) — runs BEFORE the LLM
    # so a literal value like "DSA" can't be re-extracted as a new
    # create_assignment intent from conversation history.
    session_for_assn = get_session_tg(chat_id) or {}
    assn_state_now = session_for_assn.get("state")
    if assn_state_now in ("AWAITING_ASSN_SUBJECT", "AWAITING_ASSN_TITLE",
                          "AWAITING_ASSN_BODY"):
        from src.services import assignment_service
        payload = session_for_assn.get("assn_payload") or {}

        if text.strip().lower() in ("cancel", "stop", "discard"):
            clear_session_tg(chat_id)
            _reply(chat_id, "Okay, cancelled the assignment.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        if assn_state_now == "AWAITING_ASSN_SUBJECT":
            payload["subject"] = text.strip()[:120]
            session_for_assn.update({"state": "AWAITING_ASSN_TITLE",
                                     "assn_payload": payload})
            set_session_tg(chat_id, session_for_assn)
            _reply(chat_id, "What's the title of the assignment?",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        if assn_state_now == "AWAITING_ASSN_TITLE":
            payload["title"] = text.strip()[:200]
            session_for_assn.update({"state": "AWAITING_ASSN_BODY",
                                     "assn_payload": payload})
            set_session_tg(chat_id, session_for_assn)
            _reply(chat_id,
                   "Now send the question — either <b>type it out</b> or "
                   "<b>send a photo</b> of the question paper.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        if assn_state_now == "AWAITING_ASSN_BODY":
            result = assignment_service.create(
                org_id=user["org_id"], faculty_id=user["id"],
                batch=payload.get("batch"), subject=payload.get("subject"),
                title=payload.get("title"),
                body_text=text.strip(),
            )
            clear_session_tg(chat_id)
            _reply(chat_id, result.get("message") or "Created.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

    # ---- LLM intent path (mirrors whatsapp_orchestrator._handle_text) ----
    session = get_session_tg(chat_id) or {}
    session.update({"user_id": user["id"], "org_id": user["org_id"]})
    append_history_tg(chat_id, "user", text)
    memory_append_log(user["id"], "user", text,
                      org_id=user.get("org_id"), phone=str(chat_id),
                      channel="telegram")

    context = {
        "speaker_email":      user.get("email"),
        "speaker_full_name":  user.get("full_name"),
        "channel":            "telegram",
        "state":              session.get("state"),
        "pending_upload_id":  session.get("pending_upload_id"),
        "history":            session.get("history", [])[-6:],
    }

    parsed_intent = LLMProcessor().process_user_intent(text, context, user_id=user["id"])
    intent = parsed_intent.get("intent")

    # Confirm/discard mappings (mirror WhatsApp orchestrator).
    if intent == "discard_upload":
        _discard_pending_tg(user, chat_id, session)
        _reply(chat_id, "Okay, I've discarded the upload.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if intent == "confirm_upload":
        result = _execute_pending_upload(user, str(chat_id), session,
                                         parsed_intent.get("entities", {}))
        clear_session_tg(chat_id)
        msg = result.get("message") or (
            "Done — message sent to everyone." if result.get("success")
            else "Couldn't complete that. " + (result.get("error") or "")
        )
        _reply(chat_id, msg, org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # ---- Timetable onboarding (M2) ----
    if intent == "onboard_timetable":
        if user.get("role") not in ("ADMIN", "FACULTY", "SUPER_ADMIN"):
            _reply(chat_id, "Only faculty/admin can publish a timetable.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        session.update({
            "user_id":  user["id"],
            "org_id":   user["org_id"],
            "state":    "AWAITING_TIMETABLE",
        })
        set_session_tg(chat_id, session)
        _reply(chat_id,
               "Great — send me your weekly timetable now. You can:\n"
               "• Send a <b>photo</b> of your printed timetable\n"
               "• Send a <b>voice note</b> describing it\n"
               "• Or <b>type it out</b> (one class per line: day, time, subject, room)\n\n"
               "I'll parse it and ask you to confirm before saving.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if intent == "discard_timetable":
        if session.get("state") in ("AWAITING_TIMETABLE", "AWAITING_TIMETABLE_CONFIRM"):
            _discard_pending_tg(user, chat_id, session)
        clear_session_tg(chat_id)
        _reply(chat_id, "Okay, I've discarded that timetable.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if intent == "confirm_timetable":
        result = _save_pending_timetable(user, str(chat_id), session)
        clear_session_tg(chat_id)
        _reply(chat_id,
               result.get("message") or ("Saved." if result.get("success") else "Couldn't save."),
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # ---- Assignments: faculty creates ----
    if intent == "create_assignment":
        if user.get("role") not in ("FACULTY", "ADMIN", "SUPER_ADMIN"):
            _reply(chat_id, "Only faculty/admin can create assignments.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        from src.services import assignment_service
        from src.services.timetable_service import who_is_busy_at

        entities = parsed_intent.get("entities", {}) or {}
        batch = (entities.get("target_batch") or "").strip()
        if not batch:
            _reply(chat_id,
                   "Which batch is this assignment for? Try "
                   "<i>create assignment for CSE-3A</i>.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        canonical = assignment_service.canonical_batch(user["org_id"], batch)
        if not canonical:
            _reply(chat_id,
                   f"I don't have a class group called <b>{batch}</b>. "
                   "Check the batch code and try again.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        batch = canonical

        # Pre-fill subject from the current period if possible.
        prefilled_subject = entities.get("target_subject")
        if not prefilled_subject:
            now_class = who_is_busy_at(user["id"])
            if now_class and now_class.get("batch") == batch:
                prefilled_subject = now_class.get("subject")

        payload = {"batch": batch}
        if prefilled_subject:
            payload["suggested_subject"] = prefilled_subject

        session.update({
            "user_id": user["id"], "org_id": user["org_id"],
            "state": "AWAITING_ASSN_SUBJECT",
            "assn_payload": payload,
        })
        set_session_tg(chat_id, session)

        prompt = (f"Creating an assignment for <b>{batch}</b>.\n\n"
                  "What subject is this for?")
        if prefilled_subject:
            prompt += (f" (Reply <code>{prefilled_subject}</code> to use the "
                       "subject you're teaching right now.)")
        _reply(chat_id, prompt,
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if intent == "submit_assignment" or intent == "list_my_assignments":
        if user.get("role") != "STUDENT":
            _reply(chat_id, "Only students can submit assignments.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        if not user.get("batch"):
            # Fall back to a fresh DB read since user dict from
            # resolve_user_by_chat_id may not include batch.
            from src.utils.db_handler import get_user_by_email
            full_user = get_user_by_email(user.get("email")) or {}
            user["batch"] = full_user.get("batch")
        if not user.get("batch"):
            _reply(chat_id,
                   "I don't know which batch you're in yet. Reply with your "
                   "batch code (e.g. <code>CSE-3A</code>).",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        from src.services import assignment_service
        items = assignment_service.list_open_for_batch(user["org_id"],
                                                       user["batch"])
        if not items:
            _reply(chat_id,
                   f"No assignments are open for <b>{user['batch']}</b> "
                   "right now.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        header = ("Pick which assignment to submit:"
                  if intent == "submit_assignment"
                  else f"Open assignments for <b>{user['batch']}</b>:")
        buttons = [
            {"id": f"pick_assn_{a['id']}",
             "title": f"{a['subject']} — {a['title']}"[:64]}
            for a in items[:10]
        ]
        try:
            send_buttons(chat_id=chat_id, body=header,
                         buttons=buttons, footer="Tap one")
            append_history_tg(chat_id, "assistant", header,
                              extra={"interactive": True})
        except Exception:
            _reply(chat_id, header + "\n" + "\n".join(
                f"• {a['subject']} — {a['title']}" for a in items[:10]),
                   org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # ---- Bulk task assignment (M4) ----
    if intent == "assign_tasks":
        if user.get("role") not in ("ADMIN", "SUPER_ADMIN"):
            _reply(chat_id, "Only admins can assign tasks in bulk.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        session.update({
            "user_id":  user["id"],
            "org_id":   user["org_id"],
            "state":    "AWAITING_TASKS",
        })
        set_session_tg(chat_id, session)
        _reply(chat_id,
               "Got it — send me the assignments now. You can:\n"
               "• Upload a <b>spreadsheet</b>, <b>PDF</b> or <b>Word</b> file\n"
               "• Send a <b>photo</b> of a printed sheet\n"
               "• Send a <b>voice note</b> describing the tasks\n"
               "• Or <b>type</b> them out\n\n"
               "I'll parse them and ask you to confirm before I notify everyone.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if intent == "discard_tasks":
        if session.get("state") in ("AWAITING_TASKS", "AWAITING_TASKS_CONFIRM"):
            _discard_pending_tg(user, chat_id, session)
        clear_session_tg(chat_id)
        _reply(chat_id, "Okay, I've discarded those tasks.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if intent == "confirm_tasks":
        result = _send_pending_tasks(user, str(chat_id), session)
        clear_session_tg(chat_id)
        _reply(chat_id,
               result.get("message") or ("Done." if result.get("success") else "Failed."),
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # Inline-typed tasks while in AWAITING_TASKS.
    if session.get("state") == "AWAITING_TASKS":
        from src.services.task_extractor import extract_tasks, summarize_tasks
        extraction = extract_tasks(text)
        tasks = extraction.get("tasks", [])
        if not tasks:
            _reply(chat_id,
                   "I couldn't pick out any tasks from that. Try one per line, "
                   "e.g. 'Prof Sharma: prepare DSA slides by Friday'.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        upload_id = persist_pending_upload(
            org_id=user["org_id"], user_id=user["id"],
            file_path=f"<typed-text:{user['id']}>",
            parsed={"kind": "text", "text": text, "tasks": tasks},
            parse_kind="tasks",
        )
        session.update({
            "state":             "AWAITING_TASKS_CONFIRM",
            "pending_upload_id": upload_id,
            "pending_tasks":     tasks,
        })
        set_session_tg(chat_id, session)
        _reply(chat_id,
               f"Here's what I got ({len(tasks)} task(s)):\n\n"
               f"{summarize_tasks(tasks)}\n\n"
               "Reply <b>send</b> to dispatch or <b>discard</b> to cancel.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # Inline-typed timetable while in AWAITING_TIMETABLE.
    if session.get("state") == "AWAITING_TIMETABLE":
        from src.services.timetable_extractor import (
            extract_timetable, summarize_timetable,
        )
        extraction = extract_timetable(text)
        entries = extraction.get("entries", [])
        if not entries:
            _reply(chat_id,
                   "I couldn't pick out any classes from that. Try one per line, "
                   "e.g. 'Mon 09:00-10:00 DSA Room 204'.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        upload_id = persist_pending_upload(
            org_id=user["org_id"], user_id=user["id"],
            file_path=f"<typed-text:{user['id']}>",
            parsed={"kind": "text", "text": text, "timetable": entries},
            parse_kind="timetable",
        )
        session.update({
            "state":             "AWAITING_TIMETABLE_CONFIRM",
            "pending_upload_id": upload_id,
            "pending_timetable": entries,
        })
        set_session_tg(chat_id, session)
        _reply(chat_id,
               f"Here's what I got:\n\n{summarize_timetable(entries)}\n\n"
               "Reply <b>save</b> to confirm or <b>discard</b> to throw it away.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # AWAITING_INTENT free-form — treat as broadcast body.
    if session.get("state") == "AWAITING_INTENT" and intent != "broadcast_notification":
        entities = parsed_intent.get("entities", {}) or {}
        entities.setdefault("body", text)
        result = _execute_pending_upload(user, str(chat_id), session, entities)
        clear_session_tg(chat_id)
        _reply(chat_id,
               result.get("message") or ("Done." if result.get("success") else "Failed."),
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # ----- Meeting scheduler card (Path 2 / NL + bare intent / edit reply) -----
    if intent == "create_meeting":
        ents = parsed_intent.get("entities", {}) or {}
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
            set_session_tg(chat_id, session)
            if draft.get("mode"):
                _send_meeting_confirm_card_tg(chat_id, user, draft)
            else:
                _send_meeting_mode_buttons_tg(chat_id, user, draft)
            return

        has_anything = any(ents.get(k) for k in
                           ("title", "start_time", "end_time", "location",
                            "agenda", "participants"))
        if not has_anything:
            session["state"] = "AWAITING_MEETING_INPUT"
            set_session_tg(chat_id, session)
            _reply(chat_id,
                   "Sure — send me a <b>photo</b> of the circular, or just <b>tell me</b> "
                   "the details (date, time, location, attendees, agenda).",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        draft = {
            "title":      ents.get("title"),
            "start_time": ents.get("start_time"),
            "end_time":   ents.get("end_time"),
            "location":   ents.get("location"),
            "agenda":     ents.get("agenda"),
            "participants": ents.get("participants") or [],
            "mode":       ents.get("mode"),
        }
        if draft.get("mode") in ("online", "offline"):
            session.update({
                "state": "AWAITING_MEETING_CONFIRM",
                "pending_meeting_draft": draft,
            })
            set_session_tg(chat_id, session)
            _send_meeting_confirm_card_tg(chat_id, user, draft)
            return
        _stage_meeting_draft_tg(chat_id, user, draft)
        return

    # Standard intent router for everything else.
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
    _reply(chat_id, reply_msg, org_id=user.get("org_id"), user_id=user.get("id"))


# ---------------------------------------------------------------------------
# Callback (button-tap) handling
# ---------------------------------------------------------------------------

def _handle_callback(callback: Dict[str, Any]) -> None:
    """Telegram inline-keyboard tap. Mirror of whatsapp_orchestrator._handle_interactive."""
    cb_id  = callback.get("id")
    data   = callback.get("data") or ""
    msg    = callback.get("message") or {}
    chat   = msg.get("chat") or {}
    chat_id = chat.get("id")

    if not chat_id:
        answer_callback(cb_id)
        return

    user = resolve_user_by_chat_id(chat_id)
    if not user:
        answer_callback(cb_id)
        send_text(chat_id, _onboarding_message())
        return

    log_inbound(str(chat_id), "interactive", data, intent=data,
                org_id=user.get("org_id"), user_id=user.get("id"),
                metadata={"callback_id": cb_id}, channel="telegram")

    session = get_session_tg(chat_id) or {}

    # ----- Toast-emitting branches FIRST: each must call answer_callback
    # with its toast text before any other ack fires (Telegram only honors
    # the first answerCallbackQuery per tap).
    if data and data.startswith("poll_"):
        from src.services.attendance_poll import record_tap
        try:
            session_id = int(data.split("_", 1)[1])
        except (ValueError, IndexError):
            answer_callback(cb_id, "Bad button payload.")
            return
        result = record_tap(session_id, user["id"])
        toast = result.get("message") or ("Locked in ✓" if result.get("success")
                                          else "Couldn't record that.")
        answer_callback(cb_id, toast)
        return

    if data and data.startswith("mcq_"):
        from src.services.attendance_mcq import record_answer
        try:
            _, sid_s, qi_s, ch_s = data.split("_", 3)
            session_id = int(sid_s)
            q_index    = int(qi_s)
            choice     = int(ch_s)
        except (ValueError, AttributeError):
            answer_callback(cb_id, "Bad button payload.")
            return
        result = record_answer(session_id, user["id"], q_index, choice)
        toast = result.get("message") or ("Locked in ✓" if result.get("success")
                                          else "Couldn't record that.")
        answer_callback(cb_id, toast)
        return

    # All other branches: ack now (no text) so the spinner dismisses,
    # then handle the action.
    answer_callback(cb_id)

    if data == BTN_DISCARD_UPLOAD:
        _discard_pending_tg(user, chat_id, session)
        _reply(chat_id, "Okay, I've discarded the upload.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if data == BTN_CONFIRM_UPLOAD:
        result = _execute_pending_upload(user, str(chat_id), session, entities={})
        clear_session_tg(chat_id)
        _reply(chat_id,
               result.get("message") or ("Done." if result.get("success") else "Failed."),
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if data == BTN_CONFIRM_TIMETABLE:
        result = _save_pending_timetable(user, str(chat_id), session)
        clear_session_tg(chat_id)
        _reply(chat_id,
               result.get("message") or ("Saved." if result.get("success") else "Couldn't save."),
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if data == BTN_DISCARD_TIMETABLE:
        _discard_pending_tg(user, chat_id, session)
        clear_session_tg(chat_id)
        _reply(chat_id, "Okay, I've discarded that timetable.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if data == BTN_CONFIRM_TASKS:
        result = _send_pending_tasks(user, str(chat_id), session)
        clear_session_tg(chat_id)
        _reply(chat_id,
               result.get("message") or ("Done." if result.get("success") else "Failed."),
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    if data == BTN_DISCARD_TASKS:
        _discard_pending_tg(user, chat_id, session)
        clear_session_tg(chat_id)
        _reply(chat_id, "Okay, I've discarded those tasks.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # ----- Meeting scheduler card -----
    if data in (BTN_MEETING_ONLINE, BTN_MEETING_OFFLINE,
                BTN_MEETING_CONFIRM, BTN_MEETING_EDIT, BTN_MEETING_DISCARD):
        try:
            if data in (BTN_MEETING_ONLINE, BTN_MEETING_OFFLINE):
                draft = session.get("pending_meeting_draft") or {}
                if not draft:
                    _reply(chat_id,
                           "That card has expired — say <b>schedule meeting</b> "
                           "to start again.",
                           org_id=user.get("org_id"), user_id=user.get("id"))
                    return
                draft["mode"] = "online" if data == BTN_MEETING_ONLINE else "offline"
                session["pending_meeting_draft"] = draft
                session["state"] = "AWAITING_MEETING_CONFIRM"
                set_session_tg(chat_id, session)
                _send_meeting_confirm_card_tg(chat_id, user, draft)
                return

            if data == BTN_MEETING_CONFIRM:
                result = _execute_pending_meeting_tg(user, chat_id, session)
                clear_session_tg(chat_id)
                _reply(chat_id,
                       result.get("message") or
                       ("Scheduled." if result.get("success")
                        else f"Couldn't schedule: {result.get('error') or 'unknown error'}"),
                       org_id=user.get("org_id"), user_id=user.get("id"))
                return

            if data == BTN_MEETING_EDIT:
                session["state"] = "AWAITING_MEETING_EDIT"
                set_session_tg(chat_id, session)
                _reply(chat_id,
                       "What should I change? Reply with the field — e.g. "
                       "<b>time 4pm</b>, <b>room 305</b>, <b>make it online</b>.",
                       org_id=user.get("org_id"), user_id=user.get("id"))
                return

            if data == BTN_MEETING_DISCARD:
                clear_session_tg(chat_id)
                _reply(chat_id, "Okay, dropped that meeting.",
                       org_id=user.get("org_id"), user_id=user.get("id"))
                return
        except Exception as e:
            logger.exception("Meeting card button %s failed", data)
            _reply(chat_id,
                   f"⚠️ Something went wrong handling that button: {e}. "
                   "Try saying <b>schedule meeting</b> again.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

    # ----- Assignment: student picks one to submit (pick_assn_<id>) -----
    if data and data.startswith("pick_assn_"):
        from src.services import assignment_service
        try:
            assignment_id = int(data[len("pick_assn_"):])
        except ValueError:
            _reply(chat_id, "Bad button payload.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        a = assignment_service.get_assignment(assignment_id)
        if not a or a["status"] != "OPEN":
            _reply(chat_id, "That assignment is no longer open.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        if user.get("role") != "STUDENT":
            _reply(chat_id, "Only students can submit assignments.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        session.update({
            "user_id": user["id"], "org_id": user["org_id"],
            "state": "AWAITING_ASSN_FILE",
            "assn_payload": {"assignment_id": assignment_id},
        })
        set_session_tg(chat_id, session)
        _reply(chat_id,
               f"Send a photo of your work for <b>{a['subject']} — "
               f"{a['title']}</b>.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # ----- Assignment confirmation (submit_yes_<id> / submit_no_<id>) -----
    if data and (data.startswith("submit_yes_") or data.startswith("submit_no_")):
        from src.services import assignment_service
        is_yes = data.startswith("submit_yes_")
        try:
            submission_id = int(data.split("_")[-1])
        except ValueError:
            _reply(chat_id, "Bad button payload.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        if is_yes:
            result = assignment_service.confirm_submission(
                submission_id, by_user_id=user["id"])
        else:
            result = assignment_service.discard_submission(
                submission_id, by_user_id=user["id"])
        clear_session_tg(chat_id)
        _reply(chat_id, result.get("message") or
               ("Done." if result.get("success") else "Couldn't process that."),
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # ----- Deadline-nudge buttons (student side) -----
    if data and (data.startswith("nudge_almost_") or
                 data.startswith("nudge_now_")):
        is_now = data.startswith("nudge_now_")
        prefix = "nudge_now_" if is_now else "nudge_almost_"
        try:
            assignment_id = int(data[len(prefix):])
        except ValueError:
            _reply(chat_id, "Bad button payload.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        if not is_now:
            _reply(chat_id,
                   "👍 Got it — I'll stop nagging. Good luck!",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        # "I'll submit now" — pre-fill the AWAITING_ASSN_FILE state so the
        # student's next photo lands as the submission.
        from src.services.assignment_service import get_assignment
        assignment = get_assignment(assignment_id)
        if not assignment or assignment.get("status") != "OPEN":
            _reply(chat_id,
                   "That assignment isn't accepting submissions any more.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        session = session or {}
        session.update({
            "user_id": user["id"],
            "org_id": user["org_id"],
            "state": "AWAITING_ASSN_FILE",
            "assn_payload": {"assignment_id": assignment_id},
        })
        set_session_tg(chat_id, session)
        _reply(chat_id,
               f"📤 Send me a photo of your work for "
               f"<b>{assignment['subject']} — {assignment['title']}</b>. "
               "I'll register it and ask you to confirm.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # ----- MCQ generation: faculty taps "Generate 5 MCQs for X" -----
    if data and data.startswith("gen_mcq_"):
        if (user.get("role") or "").upper() not in (
            "FACULTY", "ADMIN", "SUPER_ADMIN",
        ):
            _reply(chat_id, "Only faculty/admin can generate attendance MCQs.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        try:
            _, _, rest = data.partition("gen_mcq_")
            mat_s, _, subject = rest.partition("_")
            material_id = int(mat_s)
        except (ValueError, AttributeError):
            _reply(chat_id, "Couldn't parse that material.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        if not subject:
            _reply(chat_id, "Tap the 'Generate' button on the upload card "
                            "or run <code>generate mcq attendance "
                            "&lt;subject&gt;</code>.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        from src.services import course_materials, mcq_generator
        material = course_materials.get_material(material_id)
        if not material or material["org_id"] != user.get("org_id"):
            _reply(chat_id, "I couldn't find that material in your library.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        result = mcq_generator.generate_from_text(
            subject=subject,
            text=material.get("extracted_text") or "",
            count=5,
        )
        if not result.get("success"):
            _reply(chat_id, result.get("message") or "Generation failed.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return

        questions = result["questions"]
        bank_ids = course_materials.bulk_insert_questions(
            org_id=user["org_id"],
            subject=subject,
            source_material_id=material_id,
            questions=questions,
        )

        # Show preview as a single message + Approve/Discard buttons.
        lines = [f"📝 <b>Drafted {len(questions)} MCQ(s) for {subject}</b>",
                 "<i>Review below — tap Approve to use them in the next "
                 "attendance quiz, or Discard to throw them out.</i>\n"]
        for i, q in enumerate(questions, start=1):
            lines.append(f"<b>Q{i}.</b> {q['question']}")
            for j, choice in enumerate(q["choices"]):
                marker = "✓" if j == q["correct_index"] else " "
                lines.append(f"   {marker} {chr(65 + j)}. {choice}")
            lines.append("")
        body = "\n".join(lines)

        bank_ids_csv = ",".join(str(i) for i in bank_ids)
        try:
            send_buttons(
                chat_id=chat_id, body=body,
                buttons=[
                    {"id": f"bank_approve_{bank_ids_csv}",
                     "title": "✅ Approve all"},
                    {"id": f"bank_discard_{bank_ids_csv}",
                     "title": "❌ Discard"},
                ],
                footer=f"{subject} bank",
            )
        except Exception:
            _reply(chat_id, body,
                   org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # ----- MCQ bank approve/discard -----
    if data and (data.startswith("bank_approve_") or
                 data.startswith("bank_discard_")):
        if (user.get("role") or "").upper() not in (
            "FACULTY", "ADMIN", "SUPER_ADMIN",
        ):
            _reply(chat_id, "Only faculty/admin can approve MCQs.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        approve = data.startswith("bank_approve_")
        prefix = "bank_approve_" if approve else "bank_discard_"
        try:
            ids = [int(x) for x in data[len(prefix):].split(",") if x]
        except ValueError:
            _reply(chat_id, "Bad button payload.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        from src.services import course_materials
        if approve:
            n = course_materials.approve(
                org_id=user["org_id"], ids=ids, approved_by=user["id"],
            )
            _reply(chat_id,
                   f"✅ Approved {n} question(s). Next time you say "
                   "<code>start mcq attendance &lt;subject&gt;</code>, the "
                   "quiz will use these.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
        else:
            # Soft-discard: just leave them unapproved. They stay in the
            # bank for audit but won't be picked up by start_session.
            _reply(chat_id,
                   "Discarded — these candidates won't be used. "
                   "Send a fresh PDF and try again.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
        return

    # ----- Booking approve/deny (M5) -----
    if data and data.startswith("sam_booking_"):
        from src.services.booking_service import approve_booking, deny_booking
        if user.get("role") not in ("BOOKING_AUTHORITY", "SUPER_ADMIN"):
            _reply(chat_id, "Only the booking authority can approve/deny bookings.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        try:
            action, _, raw_id = data[len("sam_booking_"):].partition("_")
            booking_id = int(raw_id)
        except (ValueError, AttributeError):
            _reply(chat_id, "Couldn't parse that booking action.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        if action == "approve":
            booking = approve_booking(booking_id, authority_id=user["id"])
            msg_out = (f"Approved booking #{booking_id}." if booking
                       else f"Booking #{booking_id} not found.")
        elif action == "deny":
            booking = deny_booking(booking_id, authority_id=user["id"])
            msg_out = (f"Denied booking #{booking_id}." if booking
                       else f"Booking #{booking_id} not found.")
        else:
            msg_out = "Unknown booking action."
        _reply(chat_id, msg_out, org_id=user.get("org_id"), user_id=user.get("id"))
        return

    logger.info("Unhandled Telegram callback data=%s from chat=%s", data, chat_id)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def handle_update(update: Dict[str, Any]) -> None:
    """
    Top-level dispatch for a single Telegram `Update` object. Called by the
    poller loop. Telegram updates are flat (no entry/changes nesting).
    """
    update_id = update.get("update_id")
    if update_id is not None and already_seen_tg(update_id):
        return

    # Callback queries (button taps)
    cb = update.get("callback_query")
    if cb:
        try:
            _handle_callback(cb)
        except Exception:
            logger.exception("Failed to handle Telegram callback")
        return

    # Plain messages (text, document, photo, voice, etc.)
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        # Other update types we don't handle yet (channel posts, etc.).
        return

    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return

    # We only handle private 1:1 chats — group support would need admin
    # permissions and a different flow.
    if chat.get("type") != "private":
        send_text(chat_id,
                  "I only work in private chats right now. Please DM me directly.")
        return

    from_user = msg.get("from") or {}
    tg_username = from_user.get("username")
    user = resolve_user_by_chat_id(chat_id)

    # Text first — covers /start before pairing.
    if "text" in msg:
        text = msg["text"] or ""
        # Audit (best-effort)
        try:
            log_inbound(str(chat_id), "text", text,
                        org_id=(user or {}).get("org_id"),
                        user_id=(user or {}).get("id"),
                        metadata={"update_id": update_id, "chat_id": chat_id,
                                  "username": tg_username},
                        channel="telegram")
        except Exception:
            pass
        _handle_text(chat_id, text, telegram_username=tg_username, user=user)
        return

    # Beyond this point the user must be paired (media flows need an org_id).
    if not user:
        send_text(chat_id, _onboarding_message())
        return

    role = user.get("role")
    if role not in ("ADMIN", "FACULTY", "STUDENT", "BOOKING_AUTHORITY", "SUPER_ADMIN"):
        _reply(chat_id, "Your account isn't permitted to drive S.A.M. via Telegram.",
               org_id=user.get("org_id"), user_id=user.get("id"))
        return

    has_media = any(k in msg for k in ("document", "photo", "voice", "audio", "video"))
    if has_media:
        # Students may upload only when actively submitting an assignment.
        student_submitting = (
            role == "STUDENT"
            and (get_session_tg(chat_id) or {}).get("state") == "AWAITING_ASSN_FILE"
            and "photo" in msg
        )
        if role not in ("ADMIN", "FACULTY", "SUPER_ADMIN") and not student_submitting:
            _reply(chat_id,
                   "Sorry — only faculty/admin can upload files. "
                   "Students can submit assignment photos by saying "
                   "<i>submit assignment</i> first.",
                   org_id=user.get("org_id"), user_id=user.get("id"))
            return
        try:
            log_inbound(str(chat_id), _media_kind(msg),
                        body=(msg.get("caption") or
                              (msg.get("document") or {}).get("file_name")),
                        org_id=user.get("org_id"), user_id=user.get("id"),
                        metadata={"update_id": update_id, "chat_id": chat_id},
                        channel="telegram")
        except Exception:
            pass
        _handle_document(user, chat_id, msg)
        return

    logger.info("Ignoring Telegram update with no text/media (chat=%s)", chat_id)


def _media_kind(msg: Dict[str, Any]) -> str:
    for k in ("document", "photo", "voice", "audio", "video"):
        if k in msg:
            return k
    return "unknown"
