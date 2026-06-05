"""
src/tasks/assignments.py
------------------------
Celery-backed deadline nudges for assignments. The Celery wrappers
themselves live in src/worker.py — this module is the pure logic, kept
out of worker.py to mirror how attendance_mcq is structured (worker.py
calls into src/services/, never the other way around).

Public API:

    schedule_reminders_for_assignment(assignment_id, due_at) -> list[str]
        Read org_settings.assignment_nudge_hours (default [24, 1]),
        schedule one nudge per offset + a closer at due_at. Returns the
        Celery task IDs. Mirrors task_service.schedule_reminders_for_task.

    dispatch_nudge(assignment_id, kind) -> str
        DM every student in the batch who has not submitted yet. Called
        from worker.dispatch_assignment_nudge.

    close_assignment(assignment_id) -> str
        Flip status to CLOSED, mark late submitters, DM faculty.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List

from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

def schedule_reminders_for_assignment(assignment_id: int,
                                      due_at: datetime) -> List[str]:
    """
    Schedule deadline nudges. Reads org_settings.assignment_nudge_hours
    via org_settings.get(); default [24, 1]. Each entry is hours before
    `due_at`. Also schedules a `closer` at due_at itself.

    Persists each scheduled fire in `assignment_reminders` so the web UI
    can show "next reminder at" later.
    """
    from src.services import org_settings
    from src.worker import celery_app

    if not isinstance(due_at, datetime):
        return []

    # Load this assignment's org_id once.
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT org_id FROM assignments WHERE id = %s;",
            (assignment_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        release_db_connection(conn)
    if not row:
        return []
    org_id = row["org_id"]

    raw_offsets = org_settings.get(org_id, "assignment_nudge_hours",
                                    default=[24, 1])
    if not isinstance(raw_offsets, list):
        raw_offsets = [24, 1]

    plan: List[tuple] = []
    for h in raw_offsets:
        try:
            hours = float(h)
        except (TypeError, ValueError):
            continue
        # Map hours → readable kind. The plan documents 24h/1h as the
        # canonical buckets; anything else gets stored as "custom".
        if abs(hours - 24) < 0.01:
            kind = "24h"
        elif abs(hours - 1) < 0.01:
            kind = "1h"
        else:
            kind = "custom"
        fires_at = due_at - timedelta(hours=hours)
        plan.append((kind, fires_at))

    # Closer at exact due_at — flips status to CLOSED, marks lates.
    plan.append(("overdue", due_at))

    job_ids: List[str] = []
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        for kind, fires_at in plan:
            if fires_at <= datetime.utcnow():
                continue
            celery_id = None
            try:
                if kind == "overdue":
                    async_result = celery_app.send_task(
                        "close_assignment",
                        args=[assignment_id],
                        eta=fires_at,
                    )
                else:
                    async_result = celery_app.send_task(
                        "dispatch_assignment_nudge",
                        args=[assignment_id, kind],
                        eta=fires_at,
                    )
                celery_id = async_result.id
                job_ids.append(celery_id)
            except Exception:
                logger.exception(
                    "Failed to enqueue assignment nudge kind=%s for assignment %s",
                    kind, assignment_id,
                )
            cur.execute(
                """
                INSERT INTO assignment_reminders
                    (assignment_id, fires_at, kind, celery_task_id)
                VALUES (%s, %s, %s, %s);
                """,
                (assignment_id, fires_at, kind, celery_id),
            )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    return job_ids


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch_nudge(assignment_id: int, kind: str) -> str:
    """
    DM every student in the batch who hasn't submitted yet. `kind` is
    just the label ("24h"/"1h"/"custom") — it changes the wording but
    not the recipient set.
    """
    from src.services.assignment_service import (
        get_assignment, submissions_for_assignment,
    )
    from src.services.telegram_service import send_buttons, send_text

    assignment = get_assignment(assignment_id)
    if not assignment:
        return f"assignment {assignment_id} not found"
    if assignment.get("status") != "OPEN":
        return f"assignment {assignment_id} not open ({assignment.get('status')})"

    snap = submissions_for_assignment(assignment_id)
    if not snap.get("success"):
        return f"assignment {assignment_id} snapshot failed"
    missing = snap["data"]["missing"]
    if not missing:
        return f"assignment {assignment_id} — nobody missing"

    title = assignment.get("title") or "Assignment"
    subject = assignment.get("subject") or ""
    due_at = assignment.get("due_at")
    when = ""
    if isinstance(due_at, datetime):
        delta = due_at - datetime.utcnow()
        if kind == "24h":
            when = "tomorrow"
        elif kind == "1h":
            when = "in about an hour"
        elif delta.total_seconds() > 0:
            hours = int(delta.total_seconds() // 3600)
            when = f"in ~{hours}h" if hours >= 1 else "in under an hour"
        else:
            when = "now"

    body = (f"⏰ <b>{subject} — {title}</b> is due {when}.\n"
            "<i>Still working on it?</i>")
    buttons = [
        {"id": f"nudge_almost_{assignment_id}",
         "title": "👌 Almost done"},
        {"id": f"nudge_now_{assignment_id}",
         "title": "📤 I'll submit now"},
    ]

    sent = 0
    for s in missing:
        chat_id = s.get("telegram_chat_id")
        if not chat_id:
            continue
        try:
            send_buttons(chat_id=int(chat_id), body=body,
                          buttons=buttons,
                          footer=f"Deadline nudge · {kind}")
            sent += 1
        except Exception:
            logger.exception("nudge dispatch failed for student %s",
                              s.get("user_id"))
            try:
                send_text(int(chat_id), body)
                sent += 1
            except Exception:
                pass

    # Mark the matching reminder row as fired.
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE assignment_reminders
               SET fired = TRUE
             WHERE assignment_id = %s AND kind = %s AND fired = FALSE;
            """,
            (assignment_id, kind),
        )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    return f"assignment {assignment_id} {kind} nudge: {sent}/{len(missing)} dispatched"


# ---------------------------------------------------------------------------
# Closer
# ---------------------------------------------------------------------------

def close_assignment(assignment_id: int) -> str:
    """
    Mark the assignment CLOSED, log the missing students for the faculty,
    DM the faculty with a final summary.
    """
    from src.services.assignment_service import (
        get_assignment, submissions_for_assignment,
    )
    from src.services.telegram_service import send_text

    assignment = get_assignment(assignment_id)
    if not assignment:
        return f"assignment {assignment_id} not found"
    if assignment.get("status") == "CLOSED":
        return f"assignment {assignment_id} already CLOSED"

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE assignments SET status='CLOSED' WHERE id = %s;",
            (assignment_id,),
        )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    snap = submissions_for_assignment(assignment_id)
    if not snap.get("success"):
        return f"assignment {assignment_id} closed (snapshot failed)"
    data = snap["data"]
    submitted = data["submitted"]
    missing = data["missing"]

    faculty_chat = None
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT telegram_chat_id FROM users WHERE id = %s;",
            (assignment.get("faculty_id"),),
        )
        row = cur.fetchone()
        cur.close()
        faculty_chat = row.get("telegram_chat_id") if row else None
    finally:
        release_db_connection(conn)

    if faculty_chat:
        title = assignment.get("title") or "Assignment"
        subject = assignment.get("subject") or ""
        lines = [
            f"📕 <b>{subject} — {title}</b> closed.",
            f"<i>{len(submitted)} submitted, {len(missing)} missed.</i>",
        ]
        if missing:
            lines.append("\n<b>Missing</b>")
            for s in missing[:30]:
                lines.append(f"  ✗ {s.get('full_name')}")
            if len(missing) > 30:
                lines.append(f"  …and {len(missing) - 30} more")
        try:
            send_text(int(faculty_chat), "\n".join(lines))
        except Exception:
            logger.exception("Couldn't DM faculty on assignment close")

    return (f"assignment {assignment_id} closed: "
            f"{len(submitted)} submitted, {len(missing)} missed")
