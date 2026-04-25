"""
WhatsApp webhook routes (Meta Cloud API).

GET  /webhooks/whatsapp   verification handshake (hub.* params)
POST /webhooks/whatsapp   inbound message dispatch

The POST endpoint always returns HTTP 200 quickly — heavy work is delegated
to the orchestrator which drops jobs onto Redis / Celery as needed.
"""

import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from src.services.whatsapp_service import verify_signature
from src.utils.config_loader import Config

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/webhooks/whatsapp")
async def whatsapp_verify(
    hub_mode:        str = Query(default="", alias="hub.mode"),
    hub_verify_token:str = Query(default="", alias="hub.verify_token"),
    hub_challenge:   str = Query(default="", alias="hub.challenge"),
):
    """
    Meta calls this once when you register the webhook. Echo back the
    challenge string if the verify token matches.
    """
    if hub_mode == "subscribe" and hub_verify_token == Config.WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhooks/whatsapp")
async def whatsapp_inbound(request: Request):
    """
    Receive inbound WhatsApp messages, verify signature, dispatch to orchestrator.
    """
    raw = await request.body()
    sig = request.headers.get("X-Hub-Signature-256")

    if not verify_signature(raw, sig):
        logger.warning("WhatsApp webhook: invalid signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Imported lazily so the route module loads even if Redis is unreachable
    # at boot — orchestrator handles its own dependencies.
    from src.services.whatsapp_orchestrator import handle_webhook_payload

    try:
        handle_webhook_payload(payload)
    except Exception:
        logger.exception("WhatsApp orchestrator raised; acknowledging anyway")

    # Always 200 — Meta retries aggressively otherwise.
    return {"received": True}
