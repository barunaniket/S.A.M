"""
telegram_service.py
-------------------
Thin wrapper over the Telegram Bot API. Mirrors the public surface of
whatsapp_service.py so the orchestrator can swap channels with minimal
code change:

    - send_text(chat_id, body)
    - send_buttons(chat_id, body, buttons)        inline keyboard
    - download_file(file_id)                      two-step getFile + binary
    - answer_callback(callback_query_id, text)    dismiss button-tap spinner
    - set_my_commands()                           /start, /help in autocomplete
    - verify_secret_token(header_value)           webhook auth (unused in poll mode)

All credentials come from src.utils.config_loader.Config:
    TELEGRAM_BOT_TOKEN
    TELEGRAM_API_BASE        (default https://api.telegram.org)
"""

import logging
from typing import Dict, List, Optional, Tuple

import httpx

from src.utils.config_loader import Config

logger = logging.getLogger(__name__)


def _bot_url(method: str) -> str:
    return f"{Config.TELEGRAM_API_BASE}/bot{Config.TELEGRAM_BOT_TOKEN}/{method}"


def _file_url(file_path: str) -> str:
    # Telegram serves the binary at a different path than the API methods.
    return f"{Config.TELEGRAM_API_BASE}/file/bot{Config.TELEGRAM_BOT_TOKEN}/{file_path}"


def is_configured() -> bool:
    return bool(Config.TELEGRAM_BOT_TOKEN)


# ---------------------------------------------------------------------------
# Outbound
# ---------------------------------------------------------------------------

def send_text(chat_id: int, body: str) -> Dict:
    """
    Send a plain-text Telegram message. Returns the Bot API JSON response
    in the same {success, data}/{success, error} shape as whatsapp_service.
    """
    if not is_configured():
        return {"success": False, "error": "TELEGRAM_BOT_TOKEN not configured"}
    if not chat_id:
        return {"success": False, "error": "Missing chat_id"}

    payload = {
        "chat_id": int(chat_id),
        "text": (body or "")[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(_bot_url("sendMessage"), json=payload)
    if resp.status_code >= 300:
        logger.error("Telegram send_text failed: %s %s", resp.status_code, resp.text)
        return {"success": False, "status": resp.status_code, "error": resp.text}
    return {"success": True, "data": resp.json()}


def send_buttons(chat_id: int, body: str,
                 buttons: List[Dict[str, str]],
                 header: Optional[str] = None,
                 footer: Optional[str] = None) -> Dict:
    """
    Send a Telegram message with an inline keyboard.

    `buttons` is a list of `{"id": "<callback_data>", "title": "<label>"}`
    matching the WhatsApp signature exactly. The `id` you set here is
    echoed back as `callback_query.data` when the user taps.

    We render one button per row (vertical stack) — closer to WhatsApp's
    reply-button feel than Telegram's default horizontal layout.
    """
    if not is_configured():
        return {"success": False, "error": "TELEGRAM_BOT_TOKEN not configured"}
    if not chat_id:
        return {"success": False, "error": "Missing chat_id"}
    if not buttons:
        return {"success": False, "error": "No buttons supplied"}

    keyboard = [
        [{
            "text": str(b["title"])[:64],
            "callback_data": str(b["id"])[:64],   # Telegram cap is 64 bytes
        }]
        for b in buttons
    ]

    text = body[:1024]
    if header:
        text = f"<b>{header}</b>\n\n{text}"
    if footer:
        text = f"{text}\n\n<i>{footer}</i>"

    payload = {
        "chat_id": int(chat_id),
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": keyboard},
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(_bot_url("sendMessage"), json=payload)
    if resp.status_code >= 300:
        logger.error("Telegram send_buttons failed: %s %s", resp.status_code, resp.text)
        return {"success": False, "status": resp.status_code, "error": resp.text}
    return {"success": True, "data": resp.json()}


def answer_callback(callback_query_id: str, text: str = "") -> None:
    """
    Acknowledge a button tap. Telegram shows a spinner on the tapped button
    until this is called — and warns in the official docs that you must do
    it within ~10 seconds.
    """
    if not is_configured() or not callback_query_id:
        return
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text[:200]
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(_bot_url("answerCallbackQuery"), json=payload)
    except Exception as e:
        logger.warning("answerCallbackQuery failed (non-fatal): %s", e)


def set_my_commands() -> Dict:
    """One-shot at startup: register the bot's command list."""
    if not is_configured():
        return {"success": False, "error": "TELEGRAM_BOT_TOKEN not configured"}
    payload = {
        "commands": [
            {"command": "start", "description": "Link your SAM account"},
            {"command": "help",  "description": "How to use SAM on Telegram"},
        ],
    }
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(_bot_url("setMyCommands"), json=payload)
    return {"success": resp.status_code < 300, "data": resp.text}


# ---------------------------------------------------------------------------
# Inbound media download — two-step (getFile metadata, then binary fetch)
# ---------------------------------------------------------------------------

def download_file(file_id: str) -> Tuple[bytes, str]:
    """
    Mirror of whatsapp_service.download_media(media_id).

    Step 1: getFile -> {file_path, file_size, ...}
    Step 2: GET {api_base}/file/bot{token}/{file_path} -> bytes

    Returns (binary, mime_type). Telegram's getFile doesn't include MIME, so
    we infer from the file extension; the orchestrator already passes the
    document's `mime_type` directly when available.
    """
    if not is_configured():
        raise RuntimeError("TELEGRAM_BOT_TOKEN not configured")
    if not file_id:
        raise ValueError("file_id is required")

    with httpx.Client(timeout=20.0) as client:
        info = client.get(_bot_url("getFile"), params={"file_id": file_id})
        info.raise_for_status()
        info_json = info.json()
        if not info_json.get("ok"):
            raise ValueError(f"getFile error: {info_json}")

        file_path = info_json.get("result", {}).get("file_path")
        if not file_path:
            raise ValueError(f"getFile returned no file_path: {info_json}")

        binary = client.get(_file_url(file_path))
        binary.raise_for_status()

        # Telegram doesn't return mime in getFile; derive from the path suffix.
        suffix = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        mime = _mime_from_ext(suffix)
        return binary.content, mime


_EXT_TO_MIME = {
    "pdf":  "application/pdf",
    "csv":  "text/csv",
    "txt":  "text/plain",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls":  "application/vnd.ms-excel",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc":  "application/msword",
    "png":  "image/png",
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "ogg":  "audio/ogg",
    "oga":  "audio/ogg",
    "mp3":  "audio/mpeg",
    "m4a":  "audio/mp4",
    "wav":  "audio/wav",
    "mp4":  "video/mp4",
}


def _mime_from_ext(ext: str) -> str:
    return _EXT_TO_MIME.get((ext or "").lower(), "application/octet-stream")


# ---------------------------------------------------------------------------
# Webhook auth — simple header equality (we run polling so this is unused
# at the moment, but kept here so a future webhook route can import it).
# ---------------------------------------------------------------------------

def verify_secret_token(header_value: Optional[str]) -> bool:
    """
    Telegram authenticates webhooks by echoing the `secret_token` you set
    via setWebhook in the `X-Telegram-Bot-Api-Secret-Token` header. Plain
    string equality, no HMAC.
    """
    expected = (Config.TELEGRAM_BOT_TOKEN or "")[:64]  # use token prefix as default secret
    if not expected or not header_value:
        return False
    # constant-time compare
    return _const_eq(expected, header_value)


def _const_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0
