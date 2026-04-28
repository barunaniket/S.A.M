"""
LLM extraction of (assignee, task, deadline) tuples from a parsed document
or audio transcript.

The admin uploads a sheet/PDF/voice memo and we get back a list ready for
admin review. Names that match an existing user are linked to user_id by the
caller (task_service.create_tasks_bulk).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


_TASKS_SYSTEM = """\
You are reading a document or transcript an administrator just uploaded that
assigns tasks to faculty/staff. Extract every assignment.

Output ONLY a JSON object — no markdown — with key:
  tasks: array of {assignee, title, description, deadline}

Rules:
- assignee is the person's name as written (e.g. "Prof Sharma", "Mehta sir",
  "Dr. Iyer"). Keep titles/honorifics — they help match against the roster.
- title is a short imperative summary (e.g. "Prepare DSA slides for Friday
  lecture"). 12 words max.
- description optional — only include extra context not in the title.
- deadline is ISO 8601 (YYYY-MM-DDTHH:MM:SS) when a date/time is mentioned;
  resolve relative dates ("by Friday", "next Monday morning") using the
  current reference time provided. If no deadline is stated, set null.
- One assignee per object. If a single sentence assigns the same task to
  multiple people, emit one object per assignee.
- Ignore boilerplate ("please find attached", greetings, sign-offs).
- If you cannot find any task assignments, return tasks=[].
"""


def _coerce_iso(s: Any) -> str | None:
    if s is None:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    # Accept "YYYY-MM-DD" alone — coerce to end-of-day.
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return f"{raw}T17:00:00"
    try:
        # Validate via fromisoformat; tolerate trailing Z.
        datetime.fromisoformat(raw.replace("Z", ""))
        return raw.replace("Z", "")
    except ValueError:
        return None


def extract_tasks(text: str, *, reference_time: datetime | None = None) -> Dict[str, Any]:
    """
    Run the LLM and return:
        {"tasks": [{assignee, title, description, deadline}, ...],
         "needs_review": bool,
         "raw": str}

    Empty list + needs_review=True on any failure.
    """
    if not text or not text.strip():
        return {"tasks": [], "needs_review": True, "error": "empty text"}

    ref = reference_time or datetime.now()
    user_msg = (
        f"Current reference time: {ref.isoformat(timespec='seconds')}\n\n"
        f"Document:\n---\n{text[:8000]}\n---"
    )

    try:
        from src.utils.config_loader import get_llm_client
        client = get_llm_client()
        raw = client.generate(_TASKS_SYSTEM, user_msg)
    except Exception as e:
        logger.warning("Task LLM extraction failed: %s", e)
        return {"tasks": [], "needs_review": True, "error": str(e)}

    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(json)?", "", cleaned)
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        data = json.loads(cleaned)
    except Exception:
        logger.warning("Task LLM returned non-JSON: %r", cleaned[:200])
        return {"tasks": [], "needs_review": True, "error": "non-json"}

    raw_tasks = data.get("tasks") or []
    cleaned_tasks: List[Dict[str, Any]] = []
    dropped = 0
    for t in raw_tasks:
        if not isinstance(t, dict):
            dropped += 1
            continue
        assignee = (t.get("assignee") or "").strip()
        title = (t.get("title") or "").strip()
        if not assignee or not title:
            dropped += 1
            continue
        cleaned_tasks.append({
            "assignee_name": assignee,
            "title": title[:300],
            "description": (t.get("description") or "").strip() or None,
            "deadline": _coerce_iso(t.get("deadline")),
        })

    return {
        "tasks": cleaned_tasks,
        "needs_review": dropped > 0 or not cleaned_tasks,
        "dropped": dropped,
    }


# ---------------------------------------------------------------------------
# Echo helper for the admin's WhatsApp confirmation.
# ---------------------------------------------------------------------------

def summarize_tasks(tasks: List[Dict[str, Any]], *, max_lines: int = 6) -> str:
    if not tasks:
        return "(no task assignments detected)"
    lines = []
    for t in tasks[:max_lines]:
        deadline = f" (due {t['deadline']})" if t.get("deadline") else ""
        lines.append(f"• {t.get('assignee_name','?')}: {t['title']}{deadline}")
    if len(tasks) > max_lines:
        lines.append(f"… and {len(tasks) - max_lines} more")
    return "\n".join(lines)
