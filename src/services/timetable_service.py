"""
Per-faculty weekly timetable storage + queries.

Used by:
  - timetable onboarding flow (faculty uploads photo/voice/text → upsert)
  - student↔faculty status query ("where is Prof Sharma now?")
  - daily briefing (today's classes for a faculty)
  - class cancellation broadcast (which class is on right now)

Schema lives in scripts/migrate_v5_timetable.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz

from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
              "Friday", "Saturday", "Sunday"]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def upsert_entries(*, org_id: int, user_id: int,
                   entries: List[Dict[str, Any]],
                   source: str = "manual",
                   replace_all: bool = True) -> int:
    """
    Persist a list of timetable entries for a single user.

    With replace_all=True (default) the user's existing entries are deleted
    first — i.e. uploading a new timetable replaces the old one. This is the
    expected UX: faculty corrects the parsed grid, hits confirm, and the
    confirmed grid becomes the source of truth.

    Returns the number of rows inserted.
    """
    if not entries:
        return 0

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SET LOCAL app.org_id = %s;", (str(org_id),))

        if replace_all:
            cur.execute(
                "DELETE FROM timetable_entries WHERE user_id = %s;",
                (user_id,),
            )

        rows = 0
        for e in entries:
            cur.execute(
                """
                INSERT INTO timetable_entries
                    (org_id, user_id, day_of_week, start_time, end_time,
                     subject, room, batch, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    org_id, user_id, e["day_of_week"],
                    e["start_time"], e["end_time"],
                    e.get("subject"), e.get("room"), e.get("batch"),
                    source,
                ),
            )
            rows += 1

        conn.commit()
        cur.close()
        return rows
    except Exception:
        conn.rollback()
        raise
    finally:
        release_db_connection(conn)


def list_entries_for_user(user_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, day_of_week, start_time, end_time,
                   subject, room, batch, source
              FROM timetable_entries
             WHERE user_id = %s
             ORDER BY day_of_week, start_time;
            """,
            (user_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)


def clear_entries_for_user(user_id: int) -> int:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM timetable_entries WHERE user_id = %s;",
            (user_id,),
        )
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        return deleted
    finally:
        release_db_connection(conn)


# ---------------------------------------------------------------------------
# Status queries (student-facing)
# ---------------------------------------------------------------------------

def _resolve_when(when: Optional[datetime], tz: str = "Asia/Kolkata") -> datetime:
    """Default to "right now" in the configured timezone."""
    if when is not None:
        return when
    return datetime.now(pytz.timezone(tz)).replace(tzinfo=None)


def who_is_busy_at(user_id: int, when: Optional[datetime] = None,
                   tz: str = "Asia/Kolkata") -> Optional[Dict[str, Any]]:
    """
    Return the timetable entry the user is currently in, or None if free.
    """
    moment = _resolve_when(when, tz)
    day = moment.weekday()
    t: time = moment.time()

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, day_of_week, start_time, end_time,
                   subject, room, batch
              FROM timetable_entries
             WHERE user_id = %s
               AND day_of_week = %s
               AND start_time <= %s
               AND end_time   >  %s
             ORDER BY start_time
             LIMIT 1;
            """,
            (user_id, day, t, t),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        release_db_connection(conn)


def next_free_slot(user_id: int, *,
                   after: Optional[datetime] = None,
                   min_minutes: int = 30,
                   tz: str = "Asia/Kolkata",
                   max_lookahead_days: int = 7) -> Optional[Dict[str, Any]]:
    """
    Find the next gap >= min_minutes in the user's timetable starting from
    `after`. Returns {start: datetime, end: datetime} or None if nothing
    found in the lookahead window.

    The search is best-effort and considers only the timetable — Google
    Calendar busy time is layered on by the caller (availability_engine).
    """
    moment = _resolve_when(after, tz)
    entries = list_entries_for_user(user_id)
    if not entries:
        # No timetable = always free.
        return {"start": moment, "end": moment + timedelta(hours=1)}

    by_day: Dict[int, List[Dict[str, Any]]] = {}
    for e in entries:
        by_day.setdefault(e["day_of_week"], []).append(e)
    for day_list in by_day.values():
        day_list.sort(key=lambda e: e["start_time"])

    cursor = moment
    for _ in range(max_lookahead_days * 24):  # hourly probe, 7 days max
        day = cursor.weekday()
        ents = by_day.get(day, [])
        # Try the earliest gap that contains `cursor.time()` or starts after.
        gap_start = cursor.time()
        gap_end = time(23, 59)
        next_busy: Optional[Tuple[time, time]] = None
        for e in ents:
            s, en = e["start_time"], e["end_time"]
            if en <= gap_start:
                continue
            if s > gap_start:
                gap_end = s
                break
            # We're inside this entry — bump to its end.
            gap_start = en
        if (
            (gap_end.hour * 60 + gap_end.minute)
            - (gap_start.hour * 60 + gap_start.minute)
        ) >= min_minutes:
            start_dt = datetime.combine(cursor.date(), gap_start)
            end_dt = datetime.combine(cursor.date(), gap_end)
            return {"start": start_dt, "end": end_dt}
        # Otherwise skip to next hour.
        cursor = cursor + timedelta(hours=1)
    return None


def todays_classes(user_id: int, tz: str = "Asia/Kolkata") -> List[Dict[str, Any]]:
    moment = datetime.now(pytz.timezone(tz)).replace(tzinfo=None)
    day = moment.weekday()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT day_of_week, start_time, end_time, subject, room, batch
              FROM timetable_entries
             WHERE user_id = %s AND day_of_week = %s
             ORDER BY start_time;
            """,
            (user_id, day),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)


# ---------------------------------------------------------------------------
# Faculty resolution by name (fuzzy)
# ---------------------------------------------------------------------------

def resolve_faculty_by_name(org_id: int, query: str,
                            min_score: int = 80) -> List[Dict[str, Any]]:
    """
    Fuzzy-match a free-form name against the org's faculty roster. Returns a
    list of candidate {id, full_name, email, role, department, score} dicts
    whose score is >= min_score, sorted descending. Caller decides whether
    the top hit is unambiguous (score >> next, or only one hit).
    """
    if not query or not query.strip():
        return []

    from thefuzz import fuzz

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, full_name, email, role, department, office_location
              FROM users
             WHERE org_id = %s
               AND role IN ('FACULTY','ADMIN','SUPER_ADMIN');
            """,
            (org_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    finally:
        release_db_connection(conn)

    q = query.strip()
    out = []
    for r in rows:
        name = r.get("full_name") or ""
        if not name:
            continue
        score = max(
            fuzz.token_set_ratio(q, name),
            fuzz.partial_ratio(q.lower(), name.lower()),
        )
        if score >= min_score:
            out.append({**r, "score": int(score)})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Pretty helpers (used by intent_router replies)
# ---------------------------------------------------------------------------

def format_busy_status(faculty_name: str, entry: Optional[Dict[str, Any]],
                       at_label: str = "right now") -> str:
    if not entry:
        return f"{faculty_name} doesn't have a class scheduled {at_label}."
    parts = [f"{faculty_name} is in"]
    if entry.get("subject"):
        parts.append(f" {entry['subject']}")
    if entry.get("room"):
        parts.append(f" at {entry['room']}")
    if entry.get("batch"):
        parts.append(f" with {entry['batch']}")
    parts.append(
        f" ({entry['start_time']}–{entry['end_time']})."
    )
    return "".join(parts)
