"""
Telegram outbound queue — exact analogue of whatsapp_queue.py.

Producers (broadcast_service, worker reminder tasks, the orchestrator's
`_reply`) call queue_telegram(chat_id, body); a worker process runs
process_telegram_queue() to drain it with retries.
"""

import json
import logging
import time

import redis

from src.services.whatsapp_audit import log_outbound
from src.services.telegram_service import send_text
from src.utils.config_loader import Config

logger = logging.getLogger(__name__)

QUEUE_KEY = "telegram_queue"


def _get_redis_client():
    return redis.Redis.from_url(Config.REDIS_URL, decode_responses=True)


def queue_telegram(chat_id: int, body: str, metadata: dict = None) -> None:
    """Push a Telegram send job onto the Redis queue."""
    if not chat_id or not body:
        return
    client = _get_redis_client()
    meta = metadata or {}
    job = {
        "chat_id": int(chat_id),
        "body": body,
        "metadata": meta,
        "attempt": 0,
    }
    client.lpush(QUEUE_KEY, json.dumps(job))

    # Audit the intent-to-send. Same table as WhatsApp, distinguished by
    # the channel column added in migrate_v9_telegram.py.
    try:
        log_outbound(
            phone=str(chat_id),         # repurpose phone column for chat_id digits
            body=body,
            msg_type=meta.get("type") or "text",
            intent=meta.get("intent") or meta.get("channel"),
            org_id=meta.get("org_id"),
            user_id=meta.get("user_id"),
            metadata=meta,
            channel="telegram",
        )
    except Exception:
        pass


def process_telegram_queue(max_attempts: int = 3) -> None:
    """
    Blocking worker loop — pops jobs from Redis and sends them. Run as a
    separate process (mirror of process_whatsapp_queue).
    """
    client = _get_redis_client()
    while True:
        raw = client.rpop(QUEUE_KEY)
        if not raw:
            time.sleep(1)
            continue

        job = json.loads(raw)
        try:
            result = send_text(chat_id=job["chat_id"], body=job["body"])
            if not result.get("success"):
                raise RuntimeError(result.get("error") or "Telegram send failed")
        except Exception as e:
            attempt = job.get("attempt", 0) + 1
            logger.warning("Telegram job failed (attempt %s/%s): %s",
                           attempt, max_attempts, e)
            if attempt < max_attempts:
                job["attempt"] = attempt
                client.lpush(QUEUE_KEY, json.dumps(job))
                time.sleep(min(2 ** attempt, 30))
            else:
                logger.error("Telegram job dropped after %s attempts: %s",
                             attempt, job)
