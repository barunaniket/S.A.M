"""
assignment_service.py
---------------------
Faculty-creates / student-submits assignment flow.

Two-sided lifecycle:

  Faculty:
    1. "create assignment for CSE-3A"  → orchestrator sets AWAITING_ASSN_SUBJECT.
    2. text → set_subject() → AWAITING_ASSN_TITLE.
    3. text → set_title()   → AWAITING_ASSN_BODY.
    4. text → finalize_with_text(); OR photo → finalize_with_photo().
    5. INSERT into `assignments`, status OPEN.

  Student:
    1. "submit assignment"  → orchestrator lists open buttons via
       list_open_for_batch().
    2. tap pick_assn_<id>   → AWAITING_ASSN_FILE (state_payload={assignment_id}).
    3. photo                → register_submission() → status PENDING + Yes/No buttons.
    4. tap submit_yes_<id>  → confirm_submission() → CONFIRMED + DM faculty.
       tap submit_no_<id>   → discard_submission() → DISCARDED + delete file.

State machine itself lives in src/services/conversation_store.py (Telegram
session blob); this module is pure DB + notify.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


_LABEL_RE = re.compile(
    r"\b(assgn|assignment|assn|hw|homework)\s*\.?\s*([0-9]+)\b",
    re.IGNORECASE,
)


def parse_caption(caption: str) -> Optional[str]:
    """Pull a label like 'assgn3' / 'hw 5' out of a free-text caption."""
    if not caption:
        return None
    m = _LABEL_RE.search(caption)
    if not m:
        return None
    return f"{m.group(1).lower()}{m.group(2)}"


# ---------------------------------------------------------------------------
# Faculty: create
# ---------------------------------------------------------------------------

def canonical_batch(org_id: int, batch: str) -> Optional[str]:
    """
    Return the canonical (case-correct) batch name from user_groups, or
    None if the batch isn't recognized. Used to normalize before INSERT
    so lookups match what students have on their `users.batch` row.
    """
    if not batch:
        return None
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name FROM user_groups
             WHERE org_id = %s
               AND LOWER(name) = LOWER(%s)
             LIMIT 1;
            """,
            (org_id, batch),
        )
        row = cur.fetchone()
        cur.close()
        return row["name"] if row else None
    finally:
        release_db_connection(conn)


def create(*, org_id: int, faculty_id: int, batch: str, subject: str,
           title: str, body_text: Optional[str] = None,
           body_file_path: Optional[str] = None,
           due_at=None) -> Dict[str, Any]:
    """INSERT a new assignment row. Returns the assignment dict.

    When `due_at` is provided, also schedules deadline-nudge Celery tasks
    via src/tasks/assignments.schedule_reminders_for_assignment().
    Failure to schedule is logged but never blocks creation.
    """
    if not (body_text or body_file_path):
        return {"success": False,
                "message": "An assignment needs a body (text or photo)."}

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO assignments
                (org_id, faculty_id, batch, subject, title,
                 body_text, body_file_path, due_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, org_id, faculty_id, batch, subject, title,
                      body_text, body_file_path, due_at, status, created_at;
            """,
            (org_id, faculty_id, batch, subject, title,
             body_text, body_file_path, due_at),
        )
        row = dict(cur.fetchone())
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    if due_at:
        try:
            from src.tasks.assignments import schedule_reminders_for_assignment
            schedule_reminders_for_assignment(row["id"], due_at)
        except Exception:
            logger.exception(
                "Failed to schedule deadline nudges for assignment %s",
                row["id"],
            )

    msg = f"✓ Created <b>{title}</b> for {subject} / {batch}."
    if due_at:
        try:
            msg += (f" Due {due_at.strftime('%a %d %b %H:%M')} — "
                    "I'll nudge non-submitters at 24h and 1h before.")
        except Exception:
            pass
    msg += (" Students will see it when they say "
            "<i>submit assignment</i>.")
    return {"success": True, "assignment": row, "message": msg}


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

def list_open_for_batch(org_id: int, batch: str) -> List[Dict[str, Any]]:
    """
    All OPEN assignments for a batch, joined with faculty for the display
    label. Sorted newest-first.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.id, a.subject, a.title, a.body_text, a.body_file_path,
                   a.status, a.created_at,
                   u.full_name AS faculty_name, u.id AS faculty_id,
                   u.telegram_chat_id AS faculty_chat_id
              FROM assignments a
              JOIN users u ON u.id = a.faculty_id
             WHERE a.org_id = %s
               AND a.batch  = %s
               AND a.status = 'OPEN'
             ORDER BY a.created_at DESC;
            """,
            (org_id, batch),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)


def list_open_for_faculty(org_id: int,
                          faculty_id: int) -> List[Dict[str, Any]]:
    """
    All open + recently-closed assignments authored by this faculty, with
    a precomputed (submitted, enrolled) pair. Used by the
    `list_open_assignments_for_faculty` intent and the web view at
    /app/faculty/assignments.

    The submission count is via correlated subquery; for the org sizes
    we deal with this is fast enough and avoids a GROUP BY that would
    drop assignments with zero submissions.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.id, a.subject, a.title, a.batch, a.due_at, a.status,
                   a.created_at,
                   (SELECT COUNT(*) FROM assignment_submissions s
                     WHERE s.assignment_id = a.id
                       AND s.status IN ('PENDING','CONFIRMED','REVIEWED'))
                       AS submitted,
                   (SELECT COUNT(*) FROM users u
                     WHERE u.org_id = a.org_id
                       AND u.role   = 'STUDENT'
                       AND u.batch  = a.batch)
                       AS enrolled
              FROM assignments a
             WHERE a.org_id     = %s
               AND a.faculty_id = %s
             ORDER BY (a.status = 'OPEN') DESC,
                      a.created_at DESC
             LIMIT 50;
            """,
            (org_id, faculty_id),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)


def submissions_for_assignment(assignment_id: int) -> Dict[str, Any]:
    """
    Faculty-facing: who has + has not submitted.

    Returns the standard envelope. `data` includes the assignment row,
    a `submitted` list (each {user_id, full_name, status, submitted_at,
    file_path}) and a `missing` list of users in the batch who haven't
    submitted at all.
    """
    assignment = get_assignment(assignment_id)
    if not assignment:
        return {"success": False, "message": "Assignment not found."}

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.id, s.student_id AS user_id, u.full_name,
                   s.status, s.submitted_at, s.confirmed_at,
                   s.file_path, s.caption
              FROM assignment_submissions s
              JOIN users u ON u.id = s.student_id
             WHERE s.assignment_id = %s
             ORDER BY s.submitted_at DESC;
            """,
            (assignment_id,),
        )
        submitted = [dict(r) for r in cur.fetchall()]
        submitted_ids = {r["user_id"] for r in submitted}

        cur.execute(
            """
            SELECT id AS user_id, full_name, email, telegram_chat_id
              FROM users
             WHERE org_id = %s
               AND role   = 'STUDENT'
               AND batch  = %s
             ORDER BY full_name;
            """,
            (assignment["org_id"], assignment["batch"]),
        )
        all_students = [dict(r) for r in cur.fetchall()]
        cur.close()
    finally:
        release_db_connection(conn)

    missing = [s for s in all_students if s["user_id"] not in submitted_ids]

    return {
        "success": True,
        "data": {
            "assignment": assignment,
            "submitted": submitted,
            "missing": missing,
            "submitted_count": len(submitted),
            "missing_count": len(missing),
            "enrolled": len(all_students),
        },
    }


def get_assignment(assignment_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.*, u.full_name AS faculty_name,
                   u.telegram_chat_id AS faculty_chat_id
              FROM assignments a
              JOIN users u ON u.id = a.faculty_id
             WHERE a.id = %s;
            """,
            (assignment_id,),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        release_db_connection(conn)


# ---------------------------------------------------------------------------
# Student: submit
# ---------------------------------------------------------------------------

def register_submission(*, org_id: int, assignment_id: int,
                        student_id: int, file_path: str,
                        caption: Optional[str] = None) -> Dict[str, Any]:
    """
    UPSERT a PENDING submission. Returning the row, the caller sends
    [Yes][No] buttons.

    Re-submitting (same assignment + student) overwrites the previous
    submission's file path and resets status to PENDING.
    """
    assignment = get_assignment(assignment_id)
    if not assignment or assignment["status"] != "OPEN":
        return {"success": False,
                "message": "That assignment isn't open for submissions."}

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO assignment_submissions
                (org_id, assignment_id, student_id, file_path,
                 caption, status)
            VALUES (%s, %s, %s, %s, %s, 'PENDING')
            ON CONFLICT (assignment_id, student_id) DO UPDATE
                SET file_path     = EXCLUDED.file_path,
                    caption       = EXCLUDED.caption,
                    status        = 'PENDING',
                    submitted_at  = NOW(),
                    confirmed_at  = NULL
            RETURNING id, assignment_id, student_id, file_path, caption,
                      status, submitted_at;
            """,
            (org_id, assignment_id, student_id, file_path, caption),
        )
        row = dict(cur.fetchone())
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    return {
        "success": True,
        "submission": row,
        "assignment": assignment,
        "buttons": [
            {"id": f"submit_yes_{row['id']}", "title": "✅ Yes"},
            {"id": f"submit_no_{row['id']}",  "title": "❌ No"},
        ],
        "message": (f"Submit this for <b>{assignment['subject']} — "
                    f"{assignment['title']}</b>?"),
    }


def _get_submission(submission_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.*, a.subject AS assignment_subject,
                   a.title AS assignment_title,
                   a.faculty_id AS assignment_faculty_id,
                   a.batch AS assignment_batch
              FROM assignment_submissions s
              JOIN assignments a ON a.id = s.assignment_id
             WHERE s.id = %s;
            """,
            (submission_id,),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        release_db_connection(conn)


def confirm_submission(submission_id: int, *,
                       by_user_id: int) -> Dict[str, Any]:
    """Flip to CONFIRMED, DM the faculty."""
    sub = _get_submission(submission_id)
    if not sub:
        return {"success": False, "message": "Submission not found."}
    if sub["student_id"] != by_user_id:
        return {"success": False,
                "message": "Only the student who submitted can confirm."}
    if sub["status"] == "CONFIRMED":
        return {"success": True, "already_confirmed": True,
                "message": "Already submitted ✓"}
    if sub["status"] == "DISCARDED":
        return {"success": False,
                "message": "That submission was discarded — please re-upload."}

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE assignment_submissions
               SET status = 'CONFIRMED', confirmed_at = NOW()
             WHERE id = %s;
            """,
            (submission_id,),
        )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    student_name = _student_name(sub["student_id"])
    _notify_faculty(
        faculty_id=sub["assignment_faculty_id"],
        student_name=student_name,
        batch=sub["assignment_batch"],
        subject=sub["assignment_subject"],
        title=sub["assignment_title"],
        file_path=sub["file_path"],
        caption=sub.get("caption"),
    )
    return {"success": True,
            "message": (f"✓ Submitted to your faculty for "
                        f"<b>{sub['assignment_subject']} — "
                        f"{sub['assignment_title']}</b>.")}


def discard_submission(submission_id: int, *,
                       by_user_id: int) -> Dict[str, Any]:
    """Flip to DISCARDED. Best-effort delete the file."""
    sub = _get_submission(submission_id)
    if not sub:
        return {"success": False, "message": "Submission not found."}
    if sub["student_id"] != by_user_id:
        return {"success": False,
                "message": "Only the student who submitted can discard."}

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE assignment_submissions SET status='DISCARDED' WHERE id=%s;",
            (submission_id,),
        )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    file_path = sub.get("file_path")
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            logger.warning("Could not delete submission file %s", file_path)

    return {"success": True,
            "message": "Okay, discarded — send a new photo when ready."}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _student_name(student_id: int) -> str:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT full_name, batch FROM users WHERE id = %s;",
            (student_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        release_db_connection(conn)
    if not row:
        return "A student"
    name = row["full_name"] or "A student"
    batch = row.get("batch")
    return f"{name} ({batch})" if batch else name


def _notify_faculty(*, faculty_id: int, student_name: str,
                    batch: str, subject: str, title: str,
                    file_path: str, caption: Optional[str]) -> None:
    """DM the faculty with the photo + a header. Best-effort."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT telegram_chat_id FROM users WHERE id = %s;",
            (faculty_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        release_db_connection(conn)

    if not row or not row.get("telegram_chat_id"):
        logger.info("Faculty %s has no Telegram chat — skipping DM",
                    faculty_id)
        return

    header = (f"📥 New submission from <b>{student_name}</b>\n"
              f"<i>{subject} — {title}</i>")
    if caption:
        header += f"\n\n<i>caption:</i> {caption[:200]}"

    chat_id = int(row["telegram_chat_id"])
    try:
        from src.services.telegram_service import send_photo, send_text
        if file_path and os.path.exists(file_path):
            res = send_photo(chat_id, file_path, caption=header)
            if res.get("success"):
                return
        send_text(chat_id, header + "\n\n<i>(file not attachable)</i>")
    except Exception:
        logger.exception("Faculty notification failed for submission "
                         "(faculty_id=%s)", faculty_id)
