"""
Persistent memory layer for S.A.M.

Three pieces working together:

1. **Profile JSON** (`data/memory/{user_id}.json`)
   Free-form, per-user JSON document the agent reads at every turn and writes
   to opportunistically. Holds preferences, frequent collaborators, tone, etc.
   Lives on disk because it's small, often-read, rarely-written, and the LLM
   prompt wants the whole thing inlined.

2. **conversation_log** (DB)
   Append-only ledger of every inbound/outbound message across all channels.
   Used for audit, replays, long-window context. Redis (conversation_store)
   keeps the last 12 turns hot — this is the permanent record.

3. **user_context** (DB, JSONB)
   `profile` + `learned_facts` mirror of the on-disk JSON, so SQL tooling can
   query across users (e.g. "everyone whose preferred meeting length is 30
   min"). The on-disk file is the source of truth at LLM-call time; the DB is
   updated alongside writes.

The Redis hot cache (src/services/conversation_store.py) is unchanged.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)

_MEMORY_DIR = Path(os.getenv("SAM_MEMORY_DIR", "data/memory"))


def _profile_path(user_id: int) -> Path:
    return _MEMORY_DIR / f"{user_id}.json"


def _ensure_dir() -> None:
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Profile (on-disk JSON, mirrored to user_context.profile in DB)
# ---------------------------------------------------------------------------

def load_profile(user_id: int) -> Dict[str, Any]:
    """
    Read the per-user JSON profile. Returns an empty dict on miss so callers
    can `.get()` freely.
    """
    if not user_id:
        return {}

    path = _profile_path(user_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("memory_store: failed to read profile for %s: %s", user_id, e)
        return {}


def save_profile(user_id: int, profile: Dict[str, Any]) -> None:
    """
    Persist the profile to disk AND mirror it into user_context.profile.
    """
    if not user_id:
        return

    _ensure_dir()
    path = _profile_path(user_id)
    try:
        path.write_text(json.dumps(profile, indent=2, default=str), encoding="utf-8")
    except OSError as e:
        logger.warning("memory_store: failed to write profile for %s: %s", user_id, e)
        return

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_context (user_id, profile, updated_at)
            VALUES (%s, %s::jsonb, NOW())
            ON CONFLICT (user_id) DO UPDATE
                SET profile = EXCLUDED.profile,
                    updated_at = NOW();
            """,
            (user_id, json.dumps(profile, default=str)),
        )
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        logger.exception("memory_store: failed to mirror profile to user_context")
    finally:
        release_db_connection(conn)


def update_learned_fact(user_id: int, key: str, value: Any) -> None:
    """
    Record a single learned fact. Stored in user_context.learned_facts (DB
    only — these are queryable across users; not duplicated to disk).
    """
    if not user_id or not key:
        return

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_context (user_id, learned_facts, updated_at)
            VALUES (%s, jsonb_build_object(%s, %s::jsonb), NOW())
            ON CONFLICT (user_id) DO UPDATE
                SET learned_facts = user_context.learned_facts
                                    || jsonb_build_object(%s, %s::jsonb),
                    updated_at = NOW();
            """,
            (user_id, key, json.dumps(value, default=str),
             key, json.dumps(value, default=str)),
        )
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        logger.exception("memory_store: failed to update learned fact")
    finally:
        release_db_connection(conn)


def get_learned_facts(user_id: int) -> Dict[str, Any]:
    if not user_id:
        return {}
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT learned_facts FROM user_context WHERE user_id = %s;",
            (user_id,),
        )
        row = cur.fetchone()
        cur.close()
        return (row["learned_facts"] if row else {}) or {}
    except Exception:
        conn.rollback()
        return {}
    finally:
        release_db_connection(conn)


# ---------------------------------------------------------------------------
# Conversation log (DB)
# ---------------------------------------------------------------------------

def append_log(user_id: Optional[int], role: str, content: str, *,
               org_id: Optional[int] = None,
               phone: Optional[str] = None,
               channel: str = "whatsapp",
               intent: Optional[str] = None,
               metadata: Optional[Dict[str, Any]] = None) -> None:
    """
    Persist a single conversation turn. Best-effort — never raises.
    `role` must be one of: user, assistant, system, tool.
    """
    if role not in ("user", "assistant", "system", "tool"):
        logger.warning("memory_store: ignoring invalid role %r", role)
        return

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO conversation_log
                (org_id, user_id, phone, channel, role, content, intent, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb);
            """,
            (org_id, user_id, phone, channel, role, content, intent,
             json.dumps(metadata or {}, default=str)),
        )
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        logger.exception("memory_store: failed to append conversation_log")
    finally:
        release_db_connection(conn)


def get_recent_turns(user_id: int, n: int = 20) -> List[Dict[str, Any]]:
    """
    Read the last N turns for a user, oldest-first (suitable for prompt
    inclusion). Returns [{role, content, intent, created_at}, ...].
    """
    if not user_id:
        return []
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT role, content, intent, created_at
              FROM conversation_log
             WHERE user_id = %s
             ORDER BY created_at DESC
             LIMIT %s;
            """,
            (user_id, n),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return list(reversed(rows))
    except Exception:
        conn.rollback()
        return []
    finally:
        release_db_connection(conn)


# ---------------------------------------------------------------------------
# Prompt block builder
# ---------------------------------------------------------------------------

def build_profile_prompt_block(user_id: int) -> str:
    """
    Render the user's profile + learned facts as a compact text block to
    prepend to LLM prompts. Empty string when there's nothing useful.
    """
    if not user_id:
        return ""

    profile = load_profile(user_id) or {}
    learned = get_learned_facts(user_id) or {}

    if not profile and not learned:
        return ""

    parts = ["### USER PROFILE (persistent memory):"]
    if profile:
        parts.append("Profile: " + json.dumps(profile, default=str))
    if learned:
        parts.append("Learned: " + json.dumps(learned, default=str))
    return "\n".join(parts)
