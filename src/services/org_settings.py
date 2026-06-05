"""
org_settings.py
---------------
Tiny key/value layer over the `org_settings` table created in
migrate_v13_spec.py. Values are JSONB so callers get back native Python
types (bool, int, list).

Used wherever a feature needs a per-org toggle — MCQ generation, deadline
nudge cadence, poll windows. Stays intentionally thin: no caching,
no schema, no enum. Migrations seed the defaults.

Public API:

    get(org_id, key, default=None) -> Any
    set(org_id, key, value, updated_by=None) -> None
    all_for_org(org_id) -> dict[str, Any]
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


_DEFAULTS: Dict[str, Any] = {
    "mcq_attendance_enabled": True,
    "mcq_threshold": 4,
    "mcq_window_seconds": 15,
    "assignment_nudge_hours": [24, 1],
    "poll_window_seconds": 60,
}


def get(org_id: int, key: str, default: Any = None) -> Any:
    """Fetch a single setting, falling back to baked-in defaults then `default`."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT value FROM org_settings WHERE org_id = %s AND key = %s;",
            (org_id, key),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        release_db_connection(conn)

    if row and row.get("value") is not None:
        return row["value"]
    if key in _DEFAULTS:
        return _DEFAULTS[key]
    return default


def set(org_id: int, key: str, value: Any,
        updated_by: Optional[int] = None) -> None:
    """UPSERT a setting. value is JSON-serialised."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO org_settings (org_id, key, value, updated_by, updated_at)
            VALUES (%s, %s, %s::jsonb, %s, NOW())
            ON CONFLICT (org_id, key) DO UPDATE
                SET value      = EXCLUDED.value,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = NOW();
            """,
            (org_id, key, json.dumps(value), updated_by),
        )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)


def all_for_org(org_id: int) -> Dict[str, Any]:
    """Return every setting for an org, with defaults applied for missing keys."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT key, value FROM org_settings WHERE org_id = %s;",
            (org_id,),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        release_db_connection(conn)

    out = dict(_DEFAULTS)
    for r in rows:
        out[r["key"]] = r["value"]
    return out
