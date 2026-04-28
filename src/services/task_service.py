"""
Task management — bulk creation, reminder scheduling, status updates.

Uses task_reminders to bookkeep the Celery jobs so the admin UI can show
"next reminder fires at …" and we can re-fire on demand.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.services.timetable_service import resolve_faculty_by_name
from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


REMINDER_OFFSETS = (
    ("24h", timedelta(hours=24)),
    ("4h",  timedelta(hours=4)),
    ("1h",  timedelta(hours=1)),
)


# ---------------------------------------------------------------------------
# Resolution: fuzzy-match assignee names → users
# ---------------------------------------------------------------------------

def _resolve_assignee(org_id: int, name: str) -> Optional[Dict[str, Any]]:
    """Return the top user match if unambiguous, else None (caller will keep
    the free-form name fields populated)."""
    candidates = resolve_faculty_by_name(org_id, name, min_score=78)
    if not candidates:
        return None
    if len(candidates) > 1 and (
        candidates[0]["score"] - candidates[1]["score"] < 6
    ):
        return None
    return candidates[0]


# ---------------------------------------------------------------------------
# Bulk creation
# ---------------------------------------------------------------------------

def create_tasks_bulk(*, org_id: int, assigned_by: int,
                      tasks: List[Dict[str, Any]],
                      source_upload_id: Optional[int] = None,
                      schedule_reminders: bool = True) -> List[Dict[str, Any]]:
    """
    Insert a batch of tasks. Each input dict must have at least
    `assignee_name` and `title`. Optional: `description`, `deadline` (ISO
    string or datetime).

    Returns the list of created task dicts (with `id`).
    """
    if not tasks:
        return []

    out: List[Dict[str, Any]] = []
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SET LOCAL app.org_id = %s;", (str(org_id),))

        for t in tasks:
            name = (t.get("assignee_name") or "").strip()
            if not name or not t.get("title"):
                continue
            user = _resolve_assignee(org_id, name) if name else None
            assignee_id = user["id"] if user else None
            assignee_email = user.get("email") if user else None

            deadline = t.get("deadline")
            if isinstance(deadline, str):
                try:
                    deadline = datetime.fromisoformat(deadline.replace("Z", ""))
                except ValueError:
                    deadline = None

            cur.execute(
                """
                INSERT INTO tasks
                    (org_id, assigned_by, assignee_id, assignee_name,
                     assignee_email, title, description, deadline,
                     source_upload_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (org_id, assigned_by, assignee_id, name,
                 assignee_email, t["title"], t.get("description"),
                 deadline, source_upload_id),
            )
            task_id = cur.fetchone()["id"]
            out.append({
                "id": task_id,
                "assignee_id": assignee_id,
                "assignee_name": name,
                "assignee_email": assignee_email,
                "title": t["title"],
                "deadline": deadline,
                "matched": bool(user),
            })

        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        release_db_connection(conn)

    if schedule_reminders:
        for created in out:
            if created.get("deadline"):
                schedule_reminders_for_task(created["id"], created["deadline"])

    return out


# ---------------------------------------------------------------------------
# Reminder scheduling
# ---------------------------------------------------------------------------

def schedule_reminders_for_task(task_id: int, deadline: datetime) -> List[str]:
    """
    Schedule 24h/4h/1h Celery reminders before the deadline. Records each
    job in task_reminders so it can be queried/cancelled later. Returns the
    Celery task IDs.
    """
    from src.worker import celery_app

    if not deadline:
        return []
    if not isinstance(deadline, datetime):
        return []

    job_ids: List[str] = []
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        for kind, offset in REMINDER_OFFSETS:
            fires_at = deadline - offset
            if fires_at <= datetime.utcnow():
                continue  # reminder window has already passed
            try:
                async_result = celery_app.send_task(
                    f"send_task_reminder_{kind}",
                    args=[task_id],
                    eta=fires_at,
                )
                celery_id = async_result.id
            except Exception:
                logger.exception("Failed to enqueue task reminder %s for task %s",
                                 kind, task_id)
                celery_id = None

            cur.execute(
                """
                INSERT INTO task_reminders (task_id, fires_at, kind, celery_task_id)
                VALUES (%s, %s, %s, %s);
                """,
                (task_id, fires_at, kind, celery_id),
            )
            if celery_id:
                job_ids.append(celery_id)
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        release_db_connection(conn)
    return job_ids


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def list_tasks_for_assignee(user_id: int,
                            include_done: bool = False) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        sql = (
            "SELECT id, title, description, deadline, status, "
            "       assigned_by, created_at "
            "  FROM tasks "
            " WHERE assignee_id = %s"
        )
        params: List[Any] = [user_id]
        if not include_done:
            sql += " AND status IN ('PENDING','OVERDUE')"
        sql += " ORDER BY (deadline IS NULL), deadline ASC, created_at DESC;"
        cur.execute(sql, tuple(params))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)


def list_tasks_for_assigner(user_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, assignee_id, assignee_name, assignee_email, title,
                   description, deadline, status, source_upload_id, created_at
              FROM tasks
             WHERE assigned_by = %s
             ORDER BY created_at DESC
             LIMIT 200;
            """,
            (user_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)


def get_task(task_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, org_id, assigned_by, assignee_id, assignee_name,
                   assignee_email, assignee_phone, title, description,
                   deadline, status, source_upload_id, created_at
              FROM tasks WHERE id = %s;
            """,
            (task_id,),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        release_db_connection(conn)


def update_status(task_id: int, status: str, *, by_user: int) -> bool:
    if status not in ("PENDING", "DONE", "OVERDUE", "CANCELLED"):
        raise ValueError(f"invalid status {status!r}")
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE tasks
               SET status = %s, updated_at = NOW()
             WHERE id = %s
               AND (assignee_id = %s OR assigned_by = %s);
            """,
            (status, task_id, by_user, by_user),
        )
        affected = cur.rowcount
        conn.commit()
        cur.close()
        return affected > 0
    finally:
        release_db_connection(conn)


# ---------------------------------------------------------------------------
# Personalised DM body for the kickoff message + reminders
# ---------------------------------------------------------------------------

def format_task_message(task: Dict[str, Any], *, kind: str = "assigned") -> str:
    """
    Produce the WhatsApp body for a task notification.

    kind: "assigned" (immediate) | "24h" | "4h" | "1h" | "overdue"
    """
    title = task.get("title") or "(no title)"
    deadline = task.get("deadline")
    when = ""
    if isinstance(deadline, datetime):
        when = f" (due {deadline.strftime('%a %d %b, %H:%M')})"
    elif deadline:
        when = f" (due {deadline})"

    if kind == "assigned":
        head = f"📋 New task assigned: {title}{when}."
    elif kind == "24h":
        head = f"⏰ Reminder — your task '{title}' is due in 24h{when}."
    elif kind == "4h":
        head = f"⏰ Heads-up — '{title}' is due in 4h{when}."
    elif kind == "1h":
        head = f"⏰ Final reminder — '{title}' is due in 1h."
    elif kind == "overdue":
        head = f"⚠️ Overdue — '{title}' was due{when}."
    else:
        head = f"Task update: {title}{when}."

    desc = task.get("description") or ""
    return f"{head}\n{desc}".strip()
