"""
Org-wide academic calendar (holidays / exam weeks / breaks / generic events).

The SUPER_ADMIN uploads a PDF/Excel/text academic calendar; the LLM extracts
structured events; meeting scheduling guards reject (or warn on) slots that
land inside one of those windows.

Schema lives in scripts/migrate_v6_academic_calendar.py.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


_KIND_HINTS = {
    "holiday": "HOLIDAY", "public holiday": "HOLIDAY",
    "exam": "EXAM", "exams": "EXAM", "mid-sem": "EXAM",
    "midsem": "EXAM", "end-sem": "EXAM", "endsem": "EXAM",
    "break": "BREAK", "vacation": "BREAK", "winter break": "BREAK",
    "summer break": "BREAK", "term break": "BREAK",
}


_CALENDAR_SYSTEM = """\
You are reading an academic calendar uploaded by a university. Extract every
date / date-range that affects scheduling.

Output ONLY a JSON object — no markdown — with key:
  events: array of {kind, title, start_date, end_date}

Rules:
- kind ∈ {"HOLIDAY", "EXAM", "BREAK", "EVENT"}.
- start_date and end_date are ISO YYYY-MM-DD. For a single-day event use the
  same date for both.
- title is the human-readable name (e.g. "Diwali", "Mid-sem exams",
  "Founders Day").
- Skip rows that don't affect scheduling (e.g. "fee-deadline reminder").
- If you cannot find any events, return events=[].
"""


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _coerce_date(s: Any) -> Optional[date]:
    if s is None:
        return None
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()
    raw = str(s).strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _coerce_kind(s: Any) -> str:
    raw = str(s or "").strip().upper()
    if raw in {"HOLIDAY", "EXAM", "BREAK", "EVENT"}:
        return raw
    low = raw.lower()
    for hint, mapped in _KIND_HINTS.items():
        if hint in low:
            return mapped
    return "EVENT"


def extract_events_from_text(text: str) -> List[Dict[str, Any]]:
    """
    Run the LLM over a parsed calendar (PDF/docx/Excel-as-text) and return a
    cleaned list of {kind, title, start_date, end_date}. Empty list on
    failure (caller can render a "needs manual entry" UI).
    """
    if not text or not text.strip():
        return []

    try:
        from src.utils.config_loader import get_llm_client
        client = get_llm_client()
        raw = client.generate(_CALENDAR_SYSTEM, text[:10000])
    except Exception as e:
        logger.warning("Academic calendar LLM extraction failed: %s", e)
        return []

    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(json)?", "", cleaned)
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        data = json.loads(cleaned)
    except Exception:
        logger.warning("Academic calendar LLM returned non-JSON: %r", cleaned[:200])
        return []

    raw_events = data.get("events") or []
    out: List[Dict[str, Any]] = []
    for ev in raw_events:
        if not isinstance(ev, dict):
            continue
        start = _coerce_date(ev.get("start_date"))
        end = _coerce_date(ev.get("end_date") or ev.get("start_date"))
        if not start:
            continue
        if not end or end < start:
            end = start
        title = (ev.get("title") or "").strip() or "(untitled)"
        kind = _coerce_kind(ev.get("kind"))
        out.append({
            "kind": kind,
            "title": title,
            "start_date": start,
            "end_date": end,
        })
    return out


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def import_events(*, org_id: int, events: List[Dict[str, Any]],
                  uploaded_by: Optional[int] = None,
                  source_upload_id: Optional[int] = None,
                  replace_overlapping: bool = False) -> int:
    """
    Insert events into academic_events. Returns rows inserted.

    With replace_overlapping=True, any prior event that overlaps a new event
    by date range is deleted first (useful when re-uploading a fresher
    calendar mid-year).
    """
    if not events:
        return 0
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SET LOCAL app.org_id = %s;", (str(org_id),))
        rows = 0
        for e in events:
            if replace_overlapping:
                cur.execute(
                    """
                    DELETE FROM academic_events
                     WHERE org_id = %s
                       AND start_date <= %s AND end_date >= %s;
                    """,
                    (org_id, e["end_date"], e["start_date"]),
                )
            cur.execute(
                """
                INSERT INTO academic_events
                    (org_id, kind, title, start_date, end_date,
                     source_upload_id, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (org_id, e["kind"], e["title"],
                 e["start_date"], e["end_date"],
                 source_upload_id, uploaded_by),
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


def list_events(org_id: int, *, start: Optional[date] = None,
                end: Optional[date] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        params: List[Any] = [org_id]
        sql = "SELECT id, kind, title, start_date, end_date, created_at FROM academic_events WHERE org_id = %s"
        if start:
            sql += " AND end_date >= %s"
            params.append(start)
        if end:
            sql += " AND start_date <= %s"
            params.append(end)
        sql += " ORDER BY start_date;"
        cur.execute(sql, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)


def delete_event(org_id: int, event_id: int) -> bool:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM academic_events WHERE id = %s AND org_id = %s;",
            (event_id, org_id),
        )
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        return deleted > 0
    finally:
        release_db_connection(conn)


# ---------------------------------------------------------------------------
# Scheduling guard
# ---------------------------------------------------------------------------

def is_blocked(org_id: int, when: datetime) -> Optional[Dict[str, Any]]:
    """
    Return the academic_event blocking `when` (HOLIDAY or EXAM only — BREAK
    and EVENT are informational), or None if `when` is free.
    """
    if not org_id or when is None:
        return None
    target_date = when.date() if isinstance(when, datetime) else when
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, kind, title, start_date, end_date
              FROM academic_events
             WHERE org_id = %s
               AND kind IN ('HOLIDAY','EXAM')
               AND start_date <= %s AND end_date >= %s
             ORDER BY start_date
             LIMIT 1;
            """,
            (org_id, target_date, target_date),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        release_db_connection(conn)


def block_message(event: Dict[str, Any]) -> str:
    """Friendly explanation of why a slot is blocked."""
    kind = event.get("kind", "EVENT").lower()
    label = "an exam window" if kind == "exam" else "a holiday"
    title = event.get("title") or "an academic event"
    return f"That date is {label} ({title}) — please pick a different day."
