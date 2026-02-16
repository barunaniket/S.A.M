import pytest

from src.services.meeting_state_machine import MeetingStateMachine
from src.services.lifecycle_store import (
    InMemoryMeetingRepository,
    MeetingStatus
)


@pytest.fixture
def state_machine():
    repo = InMemoryMeetingRepository()
    return MeetingStateMachine(repo)


# ============================================
# 1️⃣ Valid Transition: PENDING → SCHEDULED
# ============================================

def test_valid_transition_pending_to_scheduled(state_machine):
    response = state_machine.transition("evt_001", "SCHEDULED")

    assert response["success"] is True
    assert response["data"]["previous_status"] == "PENDING"
    assert response["data"]["new_status"] == "SCHEDULED"


# ============================================
# 2️⃣ Valid Transition: SCHEDULED → CANCELLED
# ============================================

def test_valid_transition_scheduled_to_cancelled(state_machine):
    response = state_machine.transition("evt_002", "CANCELLED")

    assert response["success"] is True
    assert response["data"]["previous_status"] == "SCHEDULED"
    assert response["data"]["new_status"] == "CANCELLED"


# ============================================
# 3️⃣ Invalid Transition: CANCELLED → SCHEDULED
# ============================================

def test_invalid_transition_from_terminal_state(state_machine):
    state_machine.transition("evt_001", "SCHEDULED")
    state_machine.transition("evt_001", "CANCELLED")

    response = state_machine.transition("evt_001", "SCHEDULED")

    assert response["success"] is False
    assert response["error_code"] == "INVALID_STATE_TRANSITION"


# ============================================
# 4️⃣ Invalid Status Value
# ============================================

def test_invalid_status_value(state_machine):
    response = state_machine.transition("evt_001", "RANDOM_STATUS")

    assert response["success"] is False
    assert response["error_code"] == "INVALID_STATUS"


# ============================================
# 5️⃣ Non-Existent Meeting
# ============================================

def test_non_existent_meeting(state_machine):
    response = state_machine.transition("evt_999", "SCHEDULED")

    assert response["success"] is False
    assert response["error_code"] == "MEETING_NOT_FOUND"


# ============================================
# 6️⃣ Terminal State Enforcement: COMPLETED
# ============================================

def test_completed_is_terminal(state_machine):
    state_machine.transition("evt_002", "COMPLETED")

    response = state_machine.transition("evt_002", "CANCELLED")

    assert response["success"] is False
    assert response["error_code"] == "INVALID_STATE_TRANSITION"
