"""
whatsapp_service.py
-------------------
Thin wrapper over Meta's WhatsApp Cloud API (Graph). Provides:

    - send_text(to, body)               outbound text message
    - send_template(to, name, params)   outbound template (for cold contact)
    - download_media(media_id)          download an inbound document/image
    - verify_signature(body, header)    HMAC-SHA256 webhook verification

All credentials come from src.utils.config_loader.Config:
    WHATSAPP_PHONE_NUMBER_ID
    WHATSAPP_ACCESS_TOKEN
    WHATSAPP_APP_SECRET
    WHATSAPP_VERIFY_TOKEN          (used at the route layer)
    WHATSAPP_GRAPH_VERSION         (default v20.0)
"""

import hashlib
import hmac
import logging
from typing import Dict, List, Optional, Tuple

import httpx

from src.utils.config_loader import Config

logger = logging.getLogger(__name__)


def _graph_url(suffix: str) -> str:
    return f"https://graph.facebook.com/{Config.WHATSAPP_GRAPH_VERSION}/{suffix.lstrip('/')}"


def _auth_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {Config.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Outbound
# ---------------------------------------------------------------------------

def _normalize_phone(phone: str) -> str:
    """Strip spaces / punctuation; Meta wants E.164 digits, no '+' required."""
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def send_text(to_phone: str, body: str) -> Dict:
    """
    Send a plain-text WhatsApp message. Returns the Graph API JSON response.
    Raises httpx.HTTPError on transport failure.
    """
    if not to_phone:
        return {"success": False, "error": "Missing recipient phone"}

    payload = {
        "messaging_product": "whatsapp",
        "to": _normalize_phone(to_phone),
        "type": "text",
        "text": {"preview_url": False, "body": body[:4096]},
    }
    url = _graph_url(f"{Config.WHATSAPP_PHONE_NUMBER_ID}/messages")
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_auth_headers(), json=payload)
    if resp.status_code >= 300:
        logger.error("WhatsApp send_text failed: %s %s", resp.status_code, resp.text)
        return {"success": False, "status": resp.status_code, "error": resp.text}
    return {"success": True, "data": resp.json()}


def send_buttons(to_phone: str, body: str,
                 buttons: List[Dict[str, str]],
                 header: Optional[str] = None,
                 footer: Optional[str] = None) -> Dict:
    """
    Send a WhatsApp interactive "reply buttons" message.

    `buttons` is a list of `{"id": "<reply_id>", "title": "<label>"}`.
    Meta caps this at three buttons; we silently truncate.

    The id you set here will be echoed back in the inbound webhook as
    `interactive.button_reply.id` — that's how the orchestrator routes
    confirm/discard/RSVP without parsing free text.
    """
    if not to_phone:
        return {"success": False, "error": "Missing recipient phone"}

    btn_payload = [
        {
            "type": "reply",
            "reply": {
                "id":    str(b["id"])[:256],
                "title": str(b["title"])[:20],
            },
        }
        for b in (buttons or [])[:3]
    ]
    if not btn_payload:
        return {"success": False, "error": "No buttons supplied"}

    interactive = {
        "type": "button",
        "body": {"text": body[:1024]},
        "action": {"buttons": btn_payload},
    }
    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}
    if footer:
        interactive["footer"] = {"text": footer[:60]}

    payload = {
        "messaging_product": "whatsapp",
        "to": _normalize_phone(to_phone),
        "type": "interactive",
        "interactive": interactive,
    }
    url = _graph_url(f"{Config.WHATSAPP_PHONE_NUMBER_ID}/messages")
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_auth_headers(), json=payload)
    if resp.status_code >= 300:
        logger.error("WhatsApp send_buttons failed: %s %s", resp.status_code, resp.text)
        return {"success": False, "status": resp.status_code, "error": resp.text}
    return {"success": True, "data": resp.json()}


def send_template(to_phone: str, template_name: str,
                  language: str = "en_US",
                  components: Optional[List[Dict]] = None) -> Dict:
    """
    Send a WhatsApp template message (required outside the 24h session window).
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": _normalize_phone(to_phone),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
        },
    }
    if components:
        payload["template"]["components"] = components

    url = _graph_url(f"{Config.WHATSAPP_PHONE_NUMBER_ID}/messages")
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=_auth_headers(), json=payload)
    if resp.status_code >= 300:
        logger.error("WhatsApp send_template failed: %s %s", resp.status_code, resp.text)
        return {"success": False, "status": resp.status_code, "error": resp.text}
    return {"success": True, "data": resp.json()}


# ---------------------------------------------------------------------------
# Inbound media download
# ---------------------------------------------------------------------------

def download_media(media_id: str) -> Tuple[bytes, str]:
    """
    Two-step Meta dance:
      1. GET /{media_id}              → returns {url, mime_type, ...}
      2. GET that url with auth       → returns binary bytes
    """
    info_url = _graph_url(media_id)
    with httpx.Client(timeout=20.0) as client:
        info = client.get(info_url, headers=_auth_headers())
        info.raise_for_status()
        info_json = info.json()

        media_url = info_json.get("url")
        mime_type = info_json.get("mime_type", "application/octet-stream")
        if not media_url:
            raise ValueError(f"No media URL in metadata: {info_json}")

        binary = client.get(media_url, headers=_auth_headers())
        binary.raise_for_status()
        return binary.content, mime_type


# ---------------------------------------------------------------------------
# Webhook verification
# ---------------------------------------------------------------------------

def verify_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """
    Verify Meta's X-Hub-Signature-256 header (format: 'sha256=<hex>') against
    the raw request body using WHATSAPP_APP_SECRET.
    """
    if not signature_header or not Config.WHATSAPP_APP_SECRET:
        return False

    expected = hmac.new(
        Config.WHATSAPP_APP_SECRET.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    received = signature_header.split("=", 1)[-1].strip()
    return hmac.compare_digest(expected, received)
