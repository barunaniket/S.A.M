import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from src.services.direct_email_service import DirectEmailService
from src.services.email_queue import queue_email
from src.services.notification_dispatcher import send_meeting_notification
from src.utils.rbac import require_roles

router = APIRouter()

_email_service = DirectEmailService()

# Sending mail on the org's behalf is a privileged action.
_EMAIL_ROLES = require_roles("FACULTY", "ADMIN", "SUPER_ADMIN")


class DirectEmailRequest(BaseModel):
    target_name: str       # display name resolved against faculty DB
    subject: str
    message_body: str


class QueueEmailRequest(BaseModel):
    to_addr: str
    subject: str
    body: str
    metadata: Optional[dict] = None


class MeetingNotificationRequest(BaseModel):
    recipient_email: str
    notification_type: str            # "invite" | "update" | "cancel"
    meeting_details: dict
    ics_attachment: Optional[str] = None


@router.post("/email/send", dependencies=[Depends(_EMAIL_ROLES)])
async def api_send_direct_email(body: DirectEmailRequest):
    """
    Send a direct email to a faculty member by resolving their display name.
    """
    # Blocking SMTP — run off the event loop.
    result = await asyncio.to_thread(
        _email_service.send_email,
        target_name=body.target_name,
        subject=body.subject,
        message_body=body.message_body,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/email/queue", dependencies=[Depends(_EMAIL_ROLES)])
async def api_queue_email(body: QueueEmailRequest):
    """
    Push an email job onto the Redis queue for async delivery.
    """
    queue_email(
        to_addr=body.to_addr,
        subject=body.subject,
        body=body.body,
        metadata=body.metadata,
    )
    return {"success": True, "message": "Email queued for delivery"}


@router.post("/email/notify", dependencies=[Depends(_EMAIL_ROLES)])
async def api_send_meeting_notification(body: MeetingNotificationRequest):
    """
    Send an HTML meeting notification email (invite / update / cancel).
    Optionally attach an ICS calendar file.
    """
    # Blocking SMTP send — run off the event loop.
    result = await asyncio.to_thread(
        send_meeting_notification,
        recipient_email=body.recipient_email,
        notification_type=body.notification_type,
        meeting_details=body.meeting_details,
        ics_attachment=body.ics_attachment,
    )
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result
