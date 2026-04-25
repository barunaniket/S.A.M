"""
broadcast_service.py
--------------------
Fan-out a message to many stakeholders across email + WhatsApp.

Two flavours:

  - broadcast_to_attendees(attendees, subject, body, channels)
        Used by the WhatsApp orchestrator after a faculty file upload.
        `attendees` is a list of {name, email, phone, role, department}.

  - broadcast_by_filters(org_id, target_role, target_department, body, channels)
        Used by the intent router when faculty says "tell all CSE students X".
"""

import logging
from typing import Any, Dict, List, Optional

from src.services.email_queue import queue_email
from src.services.whatsapp_queue import queue_whatsapp
from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


def _send_one(attendee: Dict[str, Any], subject: str, body: str,
              channels: List[str]) -> Dict[str, bool]:
    delivered = {"email": False, "whatsapp": False}

    if "email" in channels and attendee.get("email"):
        try:
            queue_email(
                to_addr=attendee["email"],
                subject=subject,
                body=body,
                metadata={"channel": "broadcast"},
            )
            delivered["email"] = True
        except Exception:
            logger.exception("queue_email failed for %s", attendee.get("email"))

    if "whatsapp" in channels and attendee.get("phone"):
        try:
            queue_whatsapp(attendee["phone"], body, metadata={"channel": "broadcast"})
            delivered["whatsapp"] = True
        except Exception:
            logger.exception("queue_whatsapp failed for %s", attendee.get("phone"))

    return delivered


def broadcast_to_attendees(attendees: List[Dict[str, Any]], subject: str,
                           body: str,
                           channels: Optional[List[str]] = None) -> Dict[str, Any]:
    if not attendees:
        return {"success": False, "message": "No attendees to message."}
    if not body:
        return {"success": False, "message": "Empty message body — nothing to send."}

    channels = channels or ["email", "whatsapp"]
    sent_email = sent_wa = 0
    for a in attendees:
        out = _send_one(a, subject, body, channels)
        sent_email += int(out["email"])
        sent_wa    += int(out["whatsapp"])

    msg = (f"Sent to {len(attendees)} contact(s): {sent_email} email(s), "
           f"{sent_wa} WhatsApp message(s) queued.")
    return {"success": True, "message": msg,
            "counts": {"total": len(attendees),
                       "email": sent_email,
                       "whatsapp": sent_wa}}


def _fetch_users(org_id: int, target_role: Optional[str],
                 target_department: Optional[str]) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SET LOCAL app.org_id = %s;", (str(org_id),))

        clauses = ["org_id = %s"]
        params: List[Any] = [org_id]
        if target_role:
            clauses.append("UPPER(role) = %s")
            params.append(target_role.upper())
        if target_department:
            clauses.append("LOWER(COALESCE(department, '')) = LOWER(%s)")
            params.append(target_department)

        sql = (
            "SELECT id, email, full_name AS name, phone_number AS phone, "
            "role, department FROM users WHERE " + " AND ".join(clauses) + ";"
        )
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        release_db_connection(conn)


def broadcast_by_filters(org_id: int, body: str,
                         subject: str = "Update from your faculty",
                         target_role: Optional[str] = None,
                         target_department: Optional[str] = None,
                         target_group_id: Optional[int] = None,
                         target_group_name: Optional[str] = None,
                         channels: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Resolve recipients by group membership (preferred when given) or by
    role/department filters, then fan out via broadcast_to_attendees.
    """
    if target_group_id or target_group_name:
        from src.services.group_service import list_members, resolve_group

        group = resolve_group(org_id, group_id=target_group_id,
                              group_name=target_group_name)
        if not group:
            ref = target_group_name or target_group_id
            return {"success": False,
                    "message": f"I couldn't find a group named '{ref}'."}
        users = list_members(org_id, group["id"])
        if not users:
            return {"success": False,
                    "message": f"Group '{group['name']}' has no members yet."}
    else:
        users = _fetch_users(org_id, target_role, target_department)

    return broadcast_to_attendees(users, subject, body, channels)
