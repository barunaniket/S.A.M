from fastapi import APIRouter, Depends, HTTPException
from src.services.lifecycle_store import lifecycle_store
from src.services.meeting_state_machine import transition_meeting_status
from src.utils.rbac import require_roles

router = APIRouter()

# Meeting lifecycle mutations — same roles as the primary /meetings routes.
_MEETING_ROLES = require_roles("FACULTY", "ADMIN", "SUPER_ADMIN")


# ---------------------------
# CREATE MEETING → PENDING
# ---------------------------
@router.post("/meeting/{meeting_id}", dependencies=[Depends(_MEETING_ROLES)])
def create_meeting(meeting_id: str):

    lifecycle_store.create_meeting(meeting_id)

    return {
        "success": True,
        "message": f"Meeting {meeting_id} created in PENDING state"
    }


# ---------------------------
# SCHEDULE → PATCH
# ---------------------------
@router.patch("/meeting/{meeting_id}/schedule", dependencies=[Depends(_MEETING_ROLES)])
def schedule_meeting(meeting_id: str):

    result = transition_meeting_status(
        meeting_id,
        "SCHEDULED"
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


# ---------------------------
# CANCEL → DELETE
# ---------------------------
@router.delete("/meeting/{meeting_id}", dependencies=[Depends(_MEETING_ROLES)])
def cancel_meeting(meeting_id: str):

    result = transition_meeting_status(
        meeting_id,
        "CANCELLED"
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result
