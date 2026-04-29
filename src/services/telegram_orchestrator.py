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
    _execute_pending_upload,
    _ext_from_mime,
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
                   telegram_chat_id, telegram_username
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

    session = get_session_tg(chat_id) or {}

    if session.get("state") == "AWAITING_TIMETABLE":
        _handle_timetable_upload_tg(user, chat_id, parsed, saved)
        return
    if session.get("state") == "AWAITING_TASKS":
        _handle_tasks_upload_tg(user, chat_id, parsed, saved)
        return

    attendees = extract_attendees(parsed)
    meeting   = extract_meeting_metadata(parsed)
    summary   = summarize(parsed, attendees)
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

    # Acknowledge the tap immediately so Telegram dismisses the spinner.
    answer_callback(cb_id)

    if not chat_id:
        return

    user = resolve_user_by_chat_id(chat_id)
    if not user:
        send_text(chat_id, _onboarding_message())
        return

    log_inbound(str(chat_id), "interactive", data, intent=data,
                org_id=user.get("org_id"), user_id=user.get("id"),
                metadata={"callback_id": cb_id}, channel="telegram")

    session = get_session_tg(chat_id) or {}

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
        if role not in ("ADMIN", "FACULTY", "SUPER_ADMIN"):
            _reply(chat_id,
                   "Sorry — only faculty/admin can upload files or voice notes. "
                   "You can still ask me questions in text.",
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
