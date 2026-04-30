"""
whatsapp_audit.py
-----------------
Append-only log of every WhatsApp turn (inbound + outbound). Used for
compliance review and debugging the orchestrator.

The writes are best-effort — failures are logged but never raise back to
the orchestrator. We don't want a missing audit table to break message
delivery.
"""

import json
import logging
from typing import Any, Dict, Optional

from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


def _normalize_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    return "".join(ch for ch in phone if ch.isdigit()) or None


def _insert(direction: str, phone: Optional[str], msg_type: Optional[str],
            body: Optional[str], intent: Optional[str],
            org_id: Optional[int], user_id: Optional[int],
            metadata: Optional[Dict[str, Any]],
            channel: str = "whatsapp") -> None:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Telegram chat IDs are pure digits but we don't want to drop the
        # leading characters of a real phone, so only normalize when channel
        # is whatsapp. Telegram passes the chat_id as a string of digits.
        phone_value = _normalize_phone(phone) if channel == "whatsapp" else (phone or None)
        cur.execute(
            """
            INSERT INTO whatsapp_audit
                (org_id, user_id, phone, direction, msg_type, body, intent, metadata, channel)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
            """,
            (
                org_id,
                user_id,
                phone_value,
                direction,
                (msg_type or "text")[:20],
                (body or "")[:4096],
                (intent or None) and intent[:40],
                json.dumps(metadata, default=str) if metadata else None,
                (channel or "whatsapp")[:16],
            ),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        # Don't let auditing break message flow — but do log loudly so it
        # surfaces in dev when the migration hasn't been applied.
        logger.warning("whatsapp_audit write failed (non-fatal): %s", e)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            release_db_connection(conn)


def log_inbound(phone: Optional[str], msg_type: str, body: Optional[str] = None,
                intent: Optional[str] = None,
                org_id: Optional[int] = None, user_id: Optional[int] = None,
                metadata: Optional[Dict[str, Any]] = None,
                channel: str = "whatsapp") -> None:
    _insert("inbound", phone, msg_type, body, intent, org_id, user_id, metadata, channel)


def log_outbound(phone: Optional[str], body: Optional[str],
                 msg_type: str = "text",
                 intent: Optional[str] = None,
                 org_id: Optional[int] = None, user_id: Optional[int] = None,
                 metadata: Optional[Dict[str, Any]] = None,
                 channel: str = "whatsapp") -> None:
    _insert("outbound", phone, msg_type, body, intent, org_id, user_id, metadata, channel)


def list_recent(org_id: int, phone: Optional[str] = None, limit: int = 100):
    """Return the last N audit rows for an org (optionally filtered by phone)."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if phone:
            digits = _normalize_phone(phone) or ""
            cur.execute(
                """
                SELECT id, org_id, user_id, phone, direction, msg_type,
                       body, intent, metadata, created_at
                  FROM whatsapp_audit
                 WHERE org_id = %s
                   AND regexp_replace(COALESCE(phone, ''), '[^0-9]', '', 'g')
                       = %s
                 ORDER BY created_at DESC
                 LIMIT %s;
                """,
                (org_id, digits, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, org_id, user_id, phone, direction, msg_type,
                       body, intent, metadata, created_at
                  FROM whatsapp_audit
                 WHERE org_id = %s
                 ORDER BY created_at DESC
                 LIMIT %s;
                """,
                (org_id, limit),
            )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)
