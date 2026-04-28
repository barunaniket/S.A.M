"""
Redis-backed WhatsApp conversation store.

Each session is keyed by the faculty's phone number (digits only). The
session JSON tracks recent message history, pending-upload reference, and
arbitrary state flags. TTL is refreshed on every interaction.
"""

import json
import time
from typing import Any, Dict, Optional

import redis

from src.utils.config_loader import Config

SESSION_TTL_SECONDS = 30 * 60     # 30 minutes
DEDUP_TTL_SECONDS   = 60 * 60     # 1 hour for inbound message-id dedup
HISTORY_LIMIT       = 12          # keep last N turns


def _client():
    return redis.Redis.from_url(Config.REDIS_URL, decode_responses=True)


def _key(phone: str) -> str:
    return f"wa:session:{phone}"


def _norm(phone: str) -> str:
    return "".join(ch for ch in (phone or "") if ch.isdigit())


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def get_session(phone: str) -> Dict[str, Any]:
    raw = _client().get(_key(_norm(phone)))
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def set_session(phone: str, data: Dict[str, Any]) -> None:
    _client().setex(_key(_norm(phone)), SESSION_TTL_SECONDS, json.dumps(data, default=str))


def clear_session(phone: str) -> None:
    _client().delete(_key(_norm(phone)))


def append_history(phone: str, role: str, content: str,
                   extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    session = get_session(phone)
    history = session.get("history", [])
    history.append({
        "role":    role,
        "content": content,
        "ts":      int(time.time()),
        **(extra or {}),
    })
    session["history"] = history[-HISTORY_LIMIT:]
    set_session(phone, session)
    return session


# ---------------------------------------------------------------------------
# Inbound message dedup (Meta retries on non-2xx)
# ---------------------------------------------------------------------------

def already_seen(message_id: str) -> bool:
    """SETNX-style guard. Returns True if we have already processed this id."""
    if not message_id:
        return False
    c = _client()
    key = f"wa:msg:{message_id}"
    # set returns True if newly created, False if already existed
    created = c.set(key, "1", nx=True, ex=DEDUP_TTL_SECONDS)
    return not created


# ---------------------------------------------------------------------------
# Telegram-channel parallels. Same Redis instance, separate key prefix so
# the two channels can't read each other's session even if a user happens
# to have a Telegram chat_id that collides with someone's phone digits.
# ---------------------------------------------------------------------------

def _key_tg(chat_id) -> str:
    return f"tg:session:{chat_id}"


def get_session_tg(chat_id) -> Dict[str, Any]:
    raw = _client().get(_key_tg(chat_id))
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def set_session_tg(chat_id, data: Dict[str, Any]) -> None:
    _client().setex(_key_tg(chat_id), SESSION_TTL_SECONDS, json.dumps(data, default=str))


def clear_session_tg(chat_id) -> None:
    _client().delete(_key_tg(chat_id))


def append_history_tg(chat_id, role: str, content: str,
                      extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    session = get_session_tg(chat_id)
    history = session.get("history", [])
    history.append({
        "role":    role,
        "content": content,
        "ts":      int(time.time()),
        **(extra or {}),
    })
    session["history"] = history[-HISTORY_LIMIT:]
    set_session_tg(chat_id, session)
    return session


def already_seen_tg(update_id) -> bool:
    """Telegram's update_id dedup — analogous to already_seen for WA msg ids."""
    if not update_id:
        return False
    c = _client()
    key = f"tg:update:{update_id}"
    created = c.set(key, "1", nx=True, ex=DEDUP_TTL_SECONDS)
    return not created
