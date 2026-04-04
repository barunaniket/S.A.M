from enum import Enum

class MeetingStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class LifecycleStore:

    def __init__(self):
        self.meetings = {}

    def create_meeting(self, meeting_id: str):
        self.meetings[meeting_id] = MeetingStatus.PENDING

    def get_status(self, meeting_id: str):
        return self.meetings.get(meeting_id)

    def update_status(self, meeting_id: str, new_status: MeetingStatus):
        if meeting_id in self.meetings:
            self.meetings[meeting_id] = new_status
            return True
        return False


# 🔥 THIS LINE WAS MISSING 🔥
lifecycle_store = LifecycleStore()
