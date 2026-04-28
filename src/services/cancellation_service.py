"""
Class cancellation broadcasts.

When a faculty says "cancel today's DSA class" the orchestrator:
  1. Looks up the matching timetable_entries row(s) for today.
  2. Resolves enrolled students via user_groups whose `name` matches the
     timetable entry's `batch` field (naming convention — see migration v8
     header for the rationale).
  3. Calls broadcast_by_filters with that group_id.
  4. Returns a summary message for the orchestrator to echo back.

Caller can optionally provide a `reason` (faculty health, technical issue,
etc.) which is appended to the broadcast body.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from src.services.broadcast_service import broadcast_by_filters
from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


def _todays_entry_for_subject(faculty_id: int, subject_query: str) -> Optional[Dict[str, Any]]:
    """
    Return today's timetable entry whose subject loosely matches `subject_query`.
    Match is case-insensitive substring; returns the first hit.
    """
    if not subject_query:
        return None
    today = datetime.now().weekday()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, day_of_week, start_time, end_time, subject, room, batch
              FROM timetable_entries
             WHERE user_id = %s
               AND day_of_week = %s
               AND LOWER(subject) LIKE %s
             ORDER BY start_time
             LIMIT 1;
            """,
            (faculty_id, today, f"%{subject_query.lower()}%"),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        release_db_connection(conn)


def _resolve_class_group_id(org_id: int, batch_label: str) -> Optional[int]:
    """
    Find a user_group whose name matches the timetable entry's batch label.
    e.g. batch="CSE-3A" → look up user_groups WHERE name='CSE-3A'.
    """
    if not batch_label:
        return None
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id FROM user_groups
             WHERE org_id = %s AND LOWER(name) = LOWER(%s)
             LIMIT 1;
            """,
            (org_id, batch_label),
        )
        row = cur.fetchone()
        cur.close()
        return row["id"] if row else None
    finally:
        release_db_connection(conn)


def cancel_class_today(*, org_id: int, faculty_id: int,
                       subject_query: str,
                       faculty_name: Optional[str] = None,
                       reason: Optional[str] = None) -> Dict[str, Any]:
    """
    Locate today's class matching `subject_query` and broadcast a
    cancellation to the enrolled students. Returns a `{success, message}`
    dict.
    """
    entry = _todays_entry_for_subject(faculty_id, subject_query)
    if not entry:
        return {
            "success": False,
            "message": f"I couldn't find a class today matching \"{subject_query}\" "
                       "in your timetable.",
        }

    batch = entry.get("batch")
    group_id = _resolve_class_group_id(org_id, batch) if batch else None

    subject = entry.get("subject") or subject_query
    room = entry.get("room")
    when = f"{entry.get('start_time')}–{entry.get('end_time')}"

    body_parts = [
        f"❌ *{subject}* class today {when}{' at ' + room if room else ''} is *cancelled*."
    ]
    if reason:
        body_parts.append(f"Reason: {reason}.")
    if faculty_name:
        body_parts.append(f"— {faculty_name}")
    body = "\n".join(body_parts)
    subject_line = f"Class cancelled: {subject}"

    if not group_id:
        return {
            "success": False,
            "message": (f"Found the class ({subject}, batch {batch}) but no "
                        f"matching student group named \"{batch}\" exists. "
                        "Create the group on /app/groups, then ask me again."),
        }

    result = broadcast_by_filters(
        org_id=org_id,
        body=body,
        subject=subject_line,
        target_group_id=group_id,
        channels=["email", "whatsapp"],
    )
    if result.get("success"):
        delivered = result.get("data", {}).get("recipient_count") if isinstance(result.get("data"), dict) else None
        msg = "Cancellation sent."
        if delivered is not None:
            msg = f"Cancellation sent to {delivered} student(s) in {batch}."
        return {"success": True, "message": msg, "data": result.get("data")}
    return {"success": False,
            "message": result.get("message") or "Couldn't send the broadcast.",
            "data": result.get("data")}
