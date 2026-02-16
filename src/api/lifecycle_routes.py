from fastapi import APIRouter, HTTPException
from src.services.lifecycle_store import lifecycle_store
from src.services.meeting_state_machine import transition_meeting_status

router = APIRouter()


# ---------------------------
# CREATE MEETING → PENDING
# ---------------------------
@router.post("/meeting/{meeting_id}")
def create_meeting(meeting_id: str):

    lifecycle_store.create_meeting(meeting_id)

    return {
        "success": True,
        "message": f"Meeting {meeting_id} created in PENDING state"
    }


# ---------------------------
# SCHEDULE → PATCH
# ---------------------------
@router.patch("/meeting/{meeting_id}/schedule")
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
@router.delete("/meeting/{meeting_id}")
def cancel_meeting(meeting_id: str):

    result = transition_meeting_status(
        meeting_id,
        "CANCELLED"
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result
