from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel
from typing import Optional

from src.services.notification import (
    create_notification,
    get_notifications,
    mark_notification_read,
)

router = APIRouter()


class CreateNotificationRequest(BaseModel):
    user_id: int
    message: str
    notification_type: str


@router.post("/notifications")
async def api_create_notification(body: CreateNotificationRequest):
    """Create a notification record for a user."""
    result = create_notification(
        user_id=body.user_id,
        message=body.message,
        notification_type=body.notification_type,
    )
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@router.get("/notifications/{user_id}")
async def api_get_notifications(
    user_id: int,
    unread_only: bool = Query(False, description="Return only unread notifications"),
):
    """Fetch notifications for a specific user."""
    result = get_notifications(user_id=user_id, unread_only=unread_only)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@router.patch("/notifications/{notification_id}/read")
async def api_mark_read(notification_id: int):
    """Mark a notification as read."""
    result = mark_notification_read(notification_id=notification_id)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result
