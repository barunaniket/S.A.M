from src.services.lifecycle_store import lifecycle_store


VALID_TRANSITIONS = {
    "PENDING": ["SCHEDULED", "CANCELLED"],
    "SCHEDULED": ["CANCELLED"],
    "CANCELLED": []
}


def transition_meeting_status(meeting_id: str, new_status: str):

    current_status = lifecycle_store.get_status(meeting_id)

    if current_status is None:
        return {
            "success": False,
            "message": "Meeting does not exist"
        }

    allowed = VALID_TRANSITIONS.get(current_status, [])

    if new_status not in allowed:
        return {
            "success": False,
            "message": f"Invalid transition from {current_status} to {new_status}"
        }

    lifecycle_store.update_status(meeting_id, new_status)

    return {
        "success": True,
        "message": f"Transitioned to {new_status}"
    }
