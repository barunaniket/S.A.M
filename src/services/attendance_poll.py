"""
attendance_poll.py
------------------
Quick Poll attendance — the start-of-class "I'm here" tap flow.

Faculty triggers a poll for a (batch, subject). The bot fans out a single
inline-keyboard button to every paired student in that batch. Each tap
upserts an attendance_records row with `status='PRESENT', source='poll'`.
Faculty closes the session manually (`close poll`); the close fans out
ABSENT rows for non-tappers and DMs the faculty a summary, with the
familiar `mark <name> present|absent` override hint.

Public API:
    start_session(faculty, batch, subject) -> dict
    record_tap(session_id, user_id)        -> dict
    close_session(session_id)              -> dict
    get_session(session_id)                -> dict | None
    latest_open_for_faculty(faculty_id)    -> dict | None
        Convenience wrapper used by the `close_poll` intent.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from src.services.attendance_common import _enrolled_students
from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def start_session(faculty: Dict[str, Any], batch: str,
                  subject: str) -> Dict[str, Any]:
    """
    Create the poll_sessions row, fan out the "I'm here" button to every
    paired student in `batch`, and return a summary the orchestrator
    relays to the faculty.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO poll_sessions (org_id, faculty_id, batch, subject)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """,
            (faculty["org_id"], faculty["id"], batch, subject),
        )
        session_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    students = _enrolled_students(faculty["org_id"], batch)

    # Fan-out the single tap button. We DM every paired student.
    from src.services.telegram_service import send_buttons

    sent = 0
    body = (f"📝 <b>Quick attendance for {subject}</b>\n"
            f"<i>Tap if you're in class with {faculty.get('full_name') or 'your faculty'}.</i>")
    button = {"id": f"poll_{session_id}", "title": "✋ I'm here"}

    for s in students:
        if not s.get("telegram_chat_id"):
            continue
        try:
            send_buttons(
                chat_id=int(s["telegram_chat_id"]),
                body=body,
                buttons=[button],
                footer=f"Quick Poll · {batch}",
            )
            sent += 1
        except Exception:
            logger.exception("Quick Poll dispatch failed for student %s",
                             s.get("id"))

    paired = sum(1 for s in students if s.get("telegram_chat_id"))
    return {
        "success": True,
        "session_id": session_id,
        "subject": subject,
        "batch": batch,
        "enrolled": len(students),
        "paired": paired,
        "dispatched": sent,
        "message": (f"✋ Started Quick Poll attendance for <b>{subject}</b> "
                    f"({batch}, {len(students)} student(s) enrolled, "
                    f"{sent} DMed). "
                    "Reply <code>close poll</code> when you're ready, or "
                    "<code>mark &lt;name&gt; present|absent</code> to override."),
    }


def record_tap(session_id: int, user_id: int) -> Dict[str, Any]:
    """
    Persist a single "I'm here" tap. Idempotent — second tap is a no-op.
    """
    session = get_session(session_id)
    if not session:
        return {"success": False, "message": "That poll no longer exists."}
    if session["status"] != "IN_PROGRESS":
        return {"success": False,
                "message": "That poll has already closed."}

    today = date.today()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO attendance_records
                (org_id, user_id, subject, class_date, status,
                 source, session_id, marked_by, overridden)
            VALUES (%s, %s, %s, %s, 'PRESENT', 'poll', %s, %s, FALSE)
            ON CONFLICT (user_id, subject, class_date) DO UPDATE
                SET status     = 'PRESENT',
                    source     = 'poll',
                    session_id = EXCLUDED.session_id,
                    marked_by  = EXCLUDED.marked_by,
                    marked_at  = NOW(),
                    overridden = FALSE;
            """,
            (session["org_id"], user_id, session["subject"], today,
             session_id, session["faculty_id"]),
        )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    return {"success": True, "message": "✓ Marked present"}


def close_session(session_id: int) -> Dict[str, Any]:
    """
    Close the poll: write ABSENT rows for any enrolled student who didn't
    tap, mark the session CLOSED, DM the faculty.
    Idempotent.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM poll_sessions WHERE id = %s FOR UPDATE;",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return {"success": False, "message": "Session not found."}
        if row["status"] == "CLOSED":
            cur.close()
            return {"success": True, "already_closed": True}
        session = dict(row)

        students = _enrolled_students(session["org_id"], session["batch"], cur=cur)
        today = date.today()

        # Pull current attendance for this (subject, date) so we know who
        # has already tapped.
        cur.execute(
            """
            SELECT user_id, status FROM attendance_records
             WHERE org_id = %s
               AND subject = %s
               AND class_date = %s;
            """,
            (session["org_id"], session["subject"], today),
        )
        present_ids = {r["user_id"] for r in cur.fetchall()
                       if r["status"] == "PRESENT"}

        results: List[Dict[str, Any]] = []
        for s in students:
            already_present = s["id"] in present_ids
            target_status = "PRESENT" if already_present else "ABSENT"
            cur.execute(
                """
                INSERT INTO attendance_records
                    (org_id, user_id, subject, class_date, status,
                     source, session_id, marked_by, overridden)
                VALUES (%s, %s, %s, %s, %s, 'poll', %s, %s, FALSE)
                ON CONFLICT (user_id, subject, class_date) DO UPDATE
                    SET status     = CASE
                                       WHEN attendance_records.status = 'PRESENT'
                                         THEN attendance_records.status
                                       ELSE EXCLUDED.status
                                     END,
                        source     = COALESCE(attendance_records.source, 'poll'),
                        session_id = COALESCE(attendance_records.session_id, EXCLUDED.session_id),
                        marked_by  = COALESCE(attendance_records.marked_by, EXCLUDED.marked_by);
                """,
                (session["org_id"], s["id"], session["subject"], today,
                 target_status, session_id, session["faculty_id"]),
            )
            results.append({"user_id": s["id"], "name": s["full_name"],
                            "status": target_status})

        cur.execute(
            "UPDATE poll_sessions SET status='CLOSED', closed_at=NOW() "
            "WHERE id = %s;",
            (session_id,),
        )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    _send_results_to_faculty(session, results)
    return {"success": True, "session_id": session_id, "results": results}


def get_session(session_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM poll_sessions WHERE id = %s;",
                    (session_id,))
        row = cur.fetchone()
        cur.close()
    finally:
        release_db_connection(conn)
    return dict(row) if row else None


def latest_open_for_faculty(faculty_id: int) -> Optional[Dict[str, Any]]:
    """The faculty's most recent IN_PROGRESS poll. Used by `close_poll`."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM poll_sessions
             WHERE faculty_id = %s
               AND status = 'IN_PROGRESS'
             ORDER BY started_at DESC
             LIMIT 1;
            """,
            (faculty_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        release_db_connection(conn)
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _send_results_to_faculty(session: Dict[str, Any],
                             results: List[Dict[str, Any]]) -> None:
    """DM the faculty with a present/absent breakdown + override hint."""
    from src.services.telegram_service import send_text

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT telegram_chat_id, full_name FROM users WHERE id = %s;",
            (session["faculty_id"],),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        release_db_connection(conn)

    if not row or not row.get("telegram_chat_id"):
        return

    present = [r for r in results if r["status"] == "PRESENT"]
    absent  = [r for r in results if r["status"] == "ABSENT"]

    lines = [f"📊 <b>{session['subject']}</b> attendance — "
             f"{session['batch']} ({len(results)} student(s))"]
    if present:
        lines.append("\n<b>Present</b>")
        for r in present:
            lines.append(f"  ✓ {r['name']}")
    if absent:
        lines.append("\n<b>Absent</b>")
        for r in absent:
            lines.append(f"  ✗ {r['name']}")
    if not results:
        lines.append("<i>No students enrolled in this batch.</i>")

    lines.append("\n<i>To override, reply with</i> "
                 "<code>mark &lt;name&gt; present</code> "
                 "<i>or</i> <code>mark &lt;name&gt; absent</code>")

    send_text(int(row["telegram_chat_id"]), "\n".join(lines))
