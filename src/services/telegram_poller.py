"""
telegram_poller.py
------------------
Long-poll loop that fetches updates from the Telegram Bot API and hands
each one to telegram_orchestrator.handle_update.

Run as a standalone process (no FastAPI request worker is held by the
long poll — keep this OUT of the main API container so a stuck network
call doesn't pin a request worker):

    python -m src.services.telegram_poller

In docker-compose this is its own service. In dev you can run it in a
tmux pane next to `uvicorn src.main:app`.

The loop survives transient network errors with exponential backoff.
Set LOG_LEVEL=DEBUG to see every update.
"""

import logging
import os
import sys
import time
from typing import Optional

import httpx

from src.services.telegram_orchestrator import handle_update
from src.services.telegram_service import is_configured, set_my_commands
from src.utils.config_loader import Config


def _setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


logger = logging.getLogger("telegram_poller")


def _api_url(method: str) -> str:
    return f"{Config.TELEGRAM_API_BASE}/bot{Config.TELEGRAM_BOT_TOKEN}/{method}"


def _drop_pending_webhook() -> None:
    """
    If a webhook is set on the bot, getUpdates returns a 409. Force-clear
    any webhook and tell Telegram to drop pending updates so we start clean.
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(_api_url("deleteWebhook"),
                        params={"drop_pending_updates": "true"})
    except Exception as e:
        logger.warning("deleteWebhook failed (non-fatal): %s", e)


def poll_loop(initial_offset: int = 0) -> None:
    """
    Blocking long-poll loop. Each call to getUpdates can hold up to
    TELEGRAM_POLL_TIMEOUT seconds before returning.
    """
    if not is_configured():
        logger.error("TELEGRAM_BOT_TOKEN not configured — refusing to start.")
        sys.exit(1)

    _drop_pending_webhook()
    try:
        set_my_commands()
    except Exception as e:
        logger.warning("set_my_commands failed (non-fatal): %s", e)

    offset = int(initial_offset or 0)
    backoff = 1
    poll_timeout = max(1, int(Config.TELEGRAM_POLL_TIMEOUT))
    http_timeout = poll_timeout + 5

    logger.info("Telegram poller started, offset=%s, poll_timeout=%ss",
                offset, poll_timeout)

    while True:
        try:
            with httpx.Client(timeout=http_timeout) as client:
                resp = client.get(
                    _api_url("getUpdates"),
                    params={"offset": offset, "timeout": poll_timeout,
                            "allowed_updates": '["message","edited_message","callback_query"]'},
                )
            resp.raise_for_status()
            payload = resp.json()
            backoff = 1   # reset on success
        except httpx.ReadTimeout:
            # Long-poll closed without updates — totally normal, keep going.
            continue
        except Exception as e:
            logger.warning("getUpdates failed: %s — backing off %ss", e, backoff)
            time.sleep(min(backoff, 30))
            backoff = min(backoff * 2, 30)
            continue

        if not payload.get("ok"):
            logger.error("getUpdates returned not-ok: %s", payload)
            time.sleep(2)
            continue

        for upd in payload.get("result", []):
            offset = (upd.get("update_id") or offset) + 1
            try:
                handle_update(upd)
            except Exception:
                logger.exception("handle_update failed for update_id=%s",
                                 upd.get("update_id"))


def main(argv: Optional[list] = None) -> None:
    _setup_logging()
    poll_loop()


if __name__ == "__main__":
    main()
