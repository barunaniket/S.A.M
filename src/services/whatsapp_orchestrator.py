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
from src.services.whatsapp_audit import log_inbound
from src.services.whatsapp_queue import queue_whatsapp
from src.services.whatsapp_service import download_media, send_buttons
from src.utils.config_loader import Config
from src.utils.db_handler import get_db_connection, release_db_connection


# Button IDs used in interactive replies. The LLM never sees these — they're
# routed straight to the action layer.
BTN_CONFIRM_UPLOAD = "sam_confirm_upload"
BTN_DISCARD_UPLOAD = "sam_discard_upload"

logger = logging.getLogger(__name__)


_MIME_EXT = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
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
            SELECT id, org_id, email, full_name, role, phone_number
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
            "Sorry — I can only handle Excel (.xlsx/.xls), PDF, text (.txt/.md), "
            "or Word (.docx) files for now. Audio/video isn't supported yet.",
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

    session = get_session(phone) or {}
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

    context = {
        "speaker_email":      user.get("email"),
        "speaker_full_name":  user.get("full_name"),
        "channel":            "whatsapp",
        "state":              session.get("state"),
        "pending_upload_id":  session.get("pending_upload_id"),
        "history":            session.get("history", [])[-6:],
    }

    parsed_intent = LLMProcessor().process_user_intent(text, context)
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
    if user.get("role") not in ("ADMIN", "FACULTY"):
        queue_whatsapp(phone, "Only faculty/admin users can drive S.A.M. via WhatsApp.",
                       metadata={"channel": "system"})
        log_inbound(phone, message.get("type", "text"),
                    body=(message.get("text") or {}).get("body"),
                    org_id=user.get("org_id"), user_id=user.get("id"),
                    metadata={"reason": "role_blocked", "role": user.get("role")})
        return

    msg_type = message.get("type")

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
