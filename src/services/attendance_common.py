"""
attendance_common.py
--------------------
Shared helpers for the two attendance modes (MCQ and Quick Poll).

Lifted out of attendance_mcq.py so attendance_poll can call into the same
roster lookup, fuzzy-match, override-by-name flow without either module
importing the other.

Public API:
    _enrolled_students(org_id, batch, cur=None) -> list[dict]
    _fuzzy_pick(candidates, query) -> dict | None
    override_attendance(*, org_id, faculty_id, subject, batch, class_date,
                        student_query, status, marked_by,
                        source='manual', session_id=None) -> dict
    latest_open_session_for_faculty(faculty_id) -> dict | None
        Returns row from mcq_sessions OR poll_sessions, whichever is more
        recent, with an extra `kind` field ('mcq' | 'poll').
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Roster lookup
# ---------------------------------------------------------------------------

def _enrolled_students(org_id: int, batch: str,
                       cur: Optional[Any] = None) -> List[Dict[str, Any]]:
    """All STUDENT rows in this org with the matching batch."""
    sql = """
        SELECT id, full_name, email, batch, telegram_chat_id, phone_number
          FROM users
         WHERE org_id = %s
           AND role = 'STUDENT'
           AND batch = %s
         ORDER BY full_name;
    """
    if cur is not None:
        cur.execute(sql, (org_id, batch))
        return [dict(r) for r in cur.fetchall()]

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(sql, (org_id, batch))
        rows = [dict(r) for r in c.fetchall()]
        c.close()
        return rows
    finally:
        release_db_connection(conn)


def _fuzzy_pick(candidates: List[Dict[str, Any]],
                query: str) -> Optional[Dict[str, Any]]:
    """Return the highest-scoring candidate, or None if nothing meaningful matches."""
    from thefuzz import fuzz

    q = (query or "").strip().lower()
    if not q:
        return None
    best = None
    best_score = 0
    for c in candidates:
        name = (c.get("full_name") or "").lower()
        score = max(
            fuzz.token_set_ratio(q, name),
            fuzz.partial_ratio(q, name),
        )
        if score > best_score:
            best_score = score
            best = c
    return best if best_score >= 65 else None


# ---------------------------------------------------------------------------
# Override (works for either MCQ or Poll sessions)
# ---------------------------------------------------------------------------

def override_attendance(*, org_id: int, faculty_id: int,
                        subject: str, batch: str, class_date: date,
                        student_query: str, status: str,
                        marked_by: int,
                        source: str = "manual",
                        session_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Flip a student's attendance for the given subject + class_date. The
    student is resolved fuzzily against the batch roster.

    Caller passes the *resolved* class context (subject, batch, date) so
    this function works equally for MCQ and Poll. When a row already
    exists it gets UPDATEd; otherwise it's INSERTed with overridden=TRUE.
    """
    status = (status or "").upper()
    if status not in ("PRESENT", "ABSENT"):
        return {"success": False,
                "message": "Status must be PRESENT or ABSENT."}

    students = _enrolled_students(org_id, batch)
    if not students:
        return {"success": False,
                "message": f"No students enrolled in {batch}."}

    target = _fuzzy_pick(students, student_query)
    if not target:
        return {"success": False,
                "message": f"I couldn't find anyone matching "
                           f"\"{student_query}\" in {batch}."}

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE attendance_records
               SET status      = %s,
                   marked_by   = %s,
                   marked_at   = NOW(),
                   overridden  = TRUE
             WHERE user_id     = %s
               AND subject     = %s
               AND class_date  = %s
            RETURNING id;
            """,
            (status, marked_by, target["id"], subject, class_date),
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                """
                INSERT INTO attendance_records
                    (org_id, user_id, subject, class_date, status,
                     source, session_id, marked_by, overridden)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (user_id, subject, class_date) DO UPDATE
                    SET status     = EXCLUDED.status,
                        marked_by  = EXCLUDED.marked_by,
                        marked_at  = NOW(),
                        overridden = TRUE;
                """,
                (org_id, target["id"], subject, class_date, status,
                 source, session_id, marked_by),
            )
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    return {"success": True,
            "student_id": target["id"],
            "student_name": target["full_name"],
            "status": status,
            "message": (f"✓ Marked <b>{target['full_name']}</b> as "
                        f"{status.lower()} for {subject} today.")}


# ---------------------------------------------------------------------------
# Session resolution for override
# ---------------------------------------------------------------------------

def latest_open_session_for_faculty(faculty_id: int) -> Optional[Dict[str, Any]]:
    """
    Return the faculty's most recent attendance session (MCQ or Poll) within
    the last 4 hours, with a `kind` field so the caller can distinguish.

    Used by the override flow: "mark Arjun present" applies to whichever
    session this faculty just ran.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, org_id, faculty_id, batch, subject, status, started_at,
                   'mcq'::text AS kind
              FROM mcq_sessions
             WHERE faculty_id = %s
               AND started_at > NOW() - INTERVAL '4 hours'
            UNION ALL
            SELECT id, org_id, faculty_id, batch, subject, status, started_at,
                   'poll'::text AS kind
              FROM poll_sessions
             WHERE faculty_id = %s
               AND started_at > NOW() - INTERVAL '4 hours'
             ORDER BY started_at DESC
             LIMIT 1;
            """,
            (faculty_id, faculty_id),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        release_db_connection(conn)
