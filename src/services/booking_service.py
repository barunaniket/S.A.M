"""
Room/lab/hall booking authority flow.

S.A.M. *never* books rooms autonomously. When a meeting needs a venue, this
service:
  1. Inserts a room_bookings row PENDING.
  2. Pings every user with role=BOOKING_AUTHORITY in the org via WhatsApp
     interactive buttons (sam_booking_approve_{id} / sam_booking_deny_{id}).
  3. On approve: marks the booking APPROVED and flips the linked meeting
     from BOOKING_PENDING → CONFIRMED. Notifies the requester.
  4. On deny: marks DENIED, notifies requester (so they can pick a new time
     or escalate).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.services.whatsapp_queue import queue_whatsapp
from src.services.whatsapp_service import send_buttons
from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _list_booking_authorities(org_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, full_name, email, phone_number
              FROM users
             WHERE org_id = %s AND role = 'BOOKING_AUTHORITY';
            """,
            (org_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)


def _insert_booking(*, org_id: int, requested_by: int,
                    room_label: Optional[str],
                    starts_at: Optional[datetime],
                    ends_at: Optional[datetime],
                    purpose: Optional[str],
                    meeting_id: Optional[str]) -> int:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO room_bookings
                (org_id, meeting_id, requested_by, room_label,
                 starts_at, ends_at, purpose)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (org_id, meeting_id, requested_by, room_label,
             starts_at, ends_at, purpose),
        )
        booking_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        return booking_id
    finally:
        release_db_connection(conn)


def get_booking(booking_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, org_id, meeting_id, requested_by, booking_authority_id,
                   room_label, starts_at, ends_at, purpose, status,
                   decided_at, notes, created_at
              FROM room_bookings WHERE id = %s;
            """,
            (booking_id,),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        release_db_connection(conn)


def list_pending(org_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT b.id, b.meeting_id, b.requested_by, b.room_label,
                   b.starts_at, b.ends_at, b.purpose, b.status, b.created_at,
                   u.full_name AS requester_name, u.email AS requester_email
              FROM room_bookings b
              LEFT JOIN users u ON u.id = b.requested_by
             WHERE b.org_id = %s AND b.status = 'PENDING'
             ORDER BY b.created_at;
            """,
            (org_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)


# ---------------------------------------------------------------------------
# Public API: create + approve/deny
# ---------------------------------------------------------------------------

def request_booking(*, org_id: int, requested_by: int,
                    room_label: Optional[str] = None,
                    starts_at: Optional[datetime] = None,
                    ends_at: Optional[datetime] = None,
                    purpose: Optional[str] = None,
                    meeting_id: Optional[str] = None,
                    requester_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Insert a PENDING room_bookings row and notify every BOOKING_AUTHORITY
    user. Returns the new booking id and the count of notifications dispatched.
    """
    booking_id = _insert_booking(
        org_id=org_id, requested_by=requested_by,
        room_label=room_label, starts_at=starts_at, ends_at=ends_at,
        purpose=purpose, meeting_id=meeting_id,
    )

    # Compose the notification.
    when = ""
    if starts_at:
        when = starts_at.strftime("%a %d %b, %H:%M")
        if ends_at:
            when += f"–{ends_at.strftime('%H:%M')}"
    body = (f"📌 *Room booking request*\n"
            f"From: {requester_name or 'a faculty member'}\n"
            f"Room: {room_label or 'TBD'}\n"
            f"When: {when or 'TBD'}\n"
            f"For: {purpose or '(no description)'}")

    notified = 0
    for ba in _list_booking_authorities(org_id):
        phone = ba.get("phone_number")
        if not phone:
            continue
        try:
            result = send_buttons(
                to_phone=phone,
                body=body,
                buttons=[
                    {"id": f"sam_booking_approve_{booking_id}", "title": "Approve"},
                    {"id": f"sam_booking_deny_{booking_id}",    "title": "Deny"},
                ],
                footer="S.A.M. booking",
            )
            if result.get("success"):
                notified += 1
        except Exception:
            logger.exception("Failed to notify booking authority %s", ba.get("id"))
            try:
                queue_whatsapp(phone, body, metadata={
                    "channel": "booking_request",
                    "booking_id": booking_id,
                    "org_id": org_id,
                })
                notified += 1
            except Exception:
                pass

    return {"success": True, "booking_id": booking_id, "notified": notified}


def _decide(booking_id: int, *, status: str,
            authority_id: int, notes: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if status not in ("APPROVED", "DENIED"):
        raise ValueError("status must be APPROVED or DENIED")

    booking = get_booking(booking_id)
    if not booking:
        return None
    if booking.get("status") != "PENDING":
        return booking  # already decided — idempotent

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE room_bookings
               SET status = %s, booking_authority_id = %s, decided_at = NOW(),
                   notes = COALESCE(%s, notes)
             WHERE id = %s;
            """,
            (status, authority_id, notes, booking_id),
        )

        # Flip linked meeting if any.
        if status == "APPROVED" and booking.get("meeting_id"):
            cur.execute(
                """
                UPDATE meetings
                   SET status = 'CONFIRMED'
                 WHERE id = %s AND status = 'BOOKING_PENDING';
                """,
                (booking["meeting_id"],),
            )
        elif status == "DENIED" and booking.get("meeting_id"):
            cur.execute(
                """
                UPDATE meetings
                   SET status = 'CANCELLED'
                 WHERE id = %s AND status = 'BOOKING_PENDING';
                """,
                (booking["meeting_id"],),
            )

        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        release_db_connection(conn)

    booking["status"] = status
    return booking


def approve_booking(booking_id: int, *, authority_id: int,
                    notes: Optional[str] = None) -> Optional[Dict[str, Any]]:
    booking = _decide(booking_id, status="APPROVED",
                      authority_id=authority_id, notes=notes)
    if booking:
        _notify_requester(booking, "approved")
    return booking


def deny_booking(booking_id: int, *, authority_id: int,
                 notes: Optional[str] = None) -> Optional[Dict[str, Any]]:
    booking = _decide(booking_id, status="DENIED",
                      authority_id=authority_id, notes=notes)
    if booking:
        _notify_requester(booking, "denied")
    return booking


def _notify_requester(booking: Dict[str, Any], decision_word: str) -> None:
    requester_id = booking.get("requested_by")
    if not requester_id:
        return
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT phone_number, email FROM users WHERE id = %s;",
            (requester_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        release_db_connection(conn)
    if not row:
        return
    body = (f"Your booking request for *{booking.get('room_label') or 'room'}*"
            f" has been {decision_word}.")
    if booking.get("notes"):
        body += f"\nNotes: {booking['notes']}"
    if row.get("phone_number"):
        try:
            queue_whatsapp(row["phone_number"], body, metadata={
                "channel": "booking_decision",
                "booking_id": booking["id"],
                "org_id": booking.get("org_id"),
                "user_id": requester_id,
            })
        except Exception:
            logger.exception("Failed to notify requester")
