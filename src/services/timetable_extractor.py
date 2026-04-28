"""
LLM-driven extraction of a faculty's weekly timetable from free-form text.

Input is the `text` field of a parsed file (image OCR / audio transcript /
PDF / docx / pasted text). Output is a list of {day_of_week, start_time,
end_time, subject, room, batch} dicts plus a `needs_review` flag.

Calls the same NVIDIA Llama 3.3 70B endpoint everything else does.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


_DAY_MAP = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


_TIMETABLE_SYSTEM = """\
You are reading a faculty member's weekly classroom timetable. The text may
come from OCR of a printed timetable photo, from a voice-note transcript, or
from a pasted document, so it can be noisy.

Output ONLY a JSON object — no markdown, no commentary — with keys:
  entries:       array of {day, start, end, subject, room, batch} objects
  needs_review:  boolean — true if the input is ambiguous, OCR-garbled,
                 or you had to guess for many cells

Rules:
- `day` is the full English weekday name (Monday … Sunday).
- `start` and `end` are 24-hour HH:MM times. Convert "9 AM" → "09:00",
  "1:30 pm" → "13:30". If only a single time is given, infer end as start+1h.
- `subject` is the subject/course name. Strip room codes from it.
- `room` is the location/room/lab if present, else null.
- `batch` is the class/section/year (e.g. "CSE-3A", "B.Tech II", "M.Sc CS"),
  else null.
- One row per period. Repeat across days when the source uses a grid.
- Skip blank cells, "FREE", "BREAK", "LUNCH" — they are not entries.
- If you cannot find any entries, return entries=[] and needs_review=true.
"""


def _coerce_time(s: Any) -> str | None:
    """Accept "09:00", "9:00", "9 AM" etc. → 24-hour HH:MM."""
    if s is None:
        return None
    raw = str(s).strip().lower()
    if not raw:
        return None

    m = re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap]m)?\s*$", raw)
    if not m:
        # Already in HH:MM:SS or other shape — try datetime parse.
        try:
            return datetime.strptime(raw, "%H:%M:%S").strftime("%H:%M")
        except ValueError:
            try:
                return datetime.strptime(raw, "%H:%M").strftime("%H:%M")
            except ValueError:
                return None

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    suffix = m.group(3)

    if suffix == "pm" and hour != 12:
        hour += 12
    elif suffix == "am" and hour == 12:
        hour = 0

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def _coerce_day(day: Any) -> int | None:
    if day is None:
        return None
    if isinstance(day, int) and 0 <= day <= 6:
        return day
    return _DAY_MAP.get(str(day).strip().lower())


def _normalize_entry(raw: Dict[str, Any]) -> Dict[str, Any] | None:
    """Validate one extracted entry. Returns None if it must be dropped."""
    day_idx = _coerce_day(raw.get("day"))
    start = _coerce_time(raw.get("start") or raw.get("start_time"))
    end = _coerce_time(raw.get("end") or raw.get("end_time"))

    if day_idx is None or not start or not end:
        return None
    if start >= end:
        return None

    subject = (raw.get("subject") or "").strip() or None
    room = (raw.get("room") or "").strip() or None
    batch = (raw.get("batch") or "").strip() or None

    return {
        "day_of_week": day_idx,
        "start_time": start,
        "end_time": end,
        "subject": subject,
        "room": room,
        "batch": batch,
    }


def extract_timetable(text: str) -> Dict[str, Any]:
    """
    Run the LLM on the parsed text and return:
        {"entries": [{day_of_week, start_time, end_time, subject, room, batch}, ...],
         "needs_review": bool,
         "raw": <whatever the model returned, for audit>}

    On any failure, returns {"entries": [], "needs_review": True, "error": "..."}.
    """
    if not text or not text.strip():
        return {"entries": [], "needs_review": True, "error": "empty text"}

    try:
        from src.utils.config_loader import get_llm_client
        client = get_llm_client()
        raw = client.generate(_TIMETABLE_SYSTEM, text[:8000])
    except Exception as e:
        logger.warning("Timetable LLM extraction failed: %s", e)
        return {"entries": [], "needs_review": True, "error": str(e)}

    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(json)?", "", cleaned)
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        data = json.loads(cleaned)
    except Exception:
        logger.warning("Timetable LLM returned non-JSON: %r", cleaned[:200])
        return {"entries": [], "needs_review": True, "error": "non-json"}

    raw_entries = data.get("entries") or []
    if not isinstance(raw_entries, list):
        return {"entries": [], "needs_review": True, "error": "entries not a list"}

    cleaned_entries: List[Dict[str, Any]] = []
    dropped = 0
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            dropped += 1
            continue
        norm = _normalize_entry(raw_entry)
        if norm is None:
            dropped += 1
            continue
        cleaned_entries.append(norm)

    needs_review = bool(data.get("needs_review")) or dropped > 0 or not cleaned_entries
    return {
        "entries": cleaned_entries,
        "needs_review": needs_review,
        "dropped": dropped,
    }


# ---------------------------------------------------------------------------
# Pretty-print helper for echoing back over WhatsApp.
# ---------------------------------------------------------------------------

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
              "Friday", "Saturday", "Sunday"]


def summarize_timetable(entries: List[Dict[str, Any]]) -> str:
    if not entries:
        return "(no entries detected)"
    by_day: Dict[int, List[Dict[str, Any]]] = {}
    for e in entries:
        by_day.setdefault(e["day_of_week"], []).append(e)
    lines = []
    for day_idx in sorted(by_day.keys()):
        lines.append(f"*{_DAY_NAMES[day_idx]}*")
        for e in sorted(by_day[day_idx], key=lambda x: x["start_time"]):
            tail = []
            if e.get("subject"):
                tail.append(e["subject"])
            if e.get("batch"):
                tail.append(e["batch"])
            if e.get("room"):
                tail.append(f"@ {e['room']}")
            label = " — ".join(tail) if tail else "(class)"
            lines.append(f"  {e['start_time']}–{e['end_time']}  {label}")
    return "\n".join(lines)
