"""
Per-user preferences (briefing time, timezone, on/off toggle).

Used by the daily-briefing tick (src/worker.py:tick_user_briefings) and the
/app/settings page.
"""

from __future__ import annotations

from datetime import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.utils.db_handler import get_db_connection, release_db_connection

router = APIRouter()


class PrefsPayload(BaseModel):
    briefing_time: Optional[str] = None        # "HH:MM"
    timezone: Optional[str] = None
    briefing_enabled: Optional[bool] = None


@router.get("/me/preferences")
def get_preferences(request: Request):
    user_id = request.state.user_id
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT briefing_time, timezone, briefing_enabled
              FROM user_preferences WHERE user_id = %s;
            """,
            (user_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        release_db_connection(conn)

    if not row:
        return {"success": True, "preferences": {
            "briefing_time": "07:00",
            "timezone": "Asia/Kolkata",
            "briefing_enabled": True,
        }}
    bt = row["briefing_time"]
    return {"success": True, "preferences": {
        "briefing_time": bt.strftime("%H:%M") if isinstance(bt, time) else str(bt),
        "timezone": row["timezone"],
        "briefing_enabled": row["briefing_enabled"],
    }}


@router.put("/me/preferences")
def set_preferences(payload: PrefsPayload, request: Request):
    user_id = request.state.user_id

    bt = None
    if payload.briefing_time:
        try:
            hh, mm = payload.briefing_time.split(":")
            bt = time(hour=int(hh), minute=int(mm))
        except (ValueError, AttributeError) as e:
            raise HTTPException(status_code=400, detail=f"Bad briefing_time: {e}")

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_preferences
                (user_id, briefing_time, timezone, briefing_enabled, updated_at)
            VALUES (%s, COALESCE(%s, '07:00'),
                    COALESCE(%s, 'Asia/Kolkata'),
                    COALESCE(%s, TRUE), NOW())
            ON CONFLICT (user_id) DO UPDATE
               SET briefing_time   = COALESCE(EXCLUDED.briefing_time, user_preferences.briefing_time),
                   timezone        = COALESCE(EXCLUDED.timezone,      user_preferences.timezone),
                   briefing_enabled= COALESCE(EXCLUDED.briefing_enabled, user_preferences.briefing_enabled),
                   updated_at      = NOW();
            """,
            (user_id, bt, payload.timezone, payload.briefing_enabled),
        )
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        release_db_connection(conn)
    return {"success": True}
