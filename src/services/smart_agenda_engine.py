from datetime import datetime, timedelta
from src.services.meeting_fetcher import fetch_meetings


def generate_daily_briefing(user_email: str, date: str) -> dict:
    """
    Generates a personalized daily meeting agenda briefing for a faculty member.

    Parameters:
    -----------
    user_email : str
        Email of faculty member

    date : str
        Date in ISO format (YYYY-MM-DD)

    Returns:
    --------
    dict:
        Worker Protocol Response
    """

    try:
        # Define day window
        day_start = f"{date}T00:00:00Z"
        day_end = f"{date}T23:59:59Z"

        #  Fetch meetings from calendar
        fetch_result = fetch_meetings(
            user_email,
            day_start,
            day_end
        )

        if not fetch_result["success"]:
            return fetch_result

        meetings = fetch_result["data"]["meetings"]

        if not meetings:
            return {
                "success": True,
                "data": {
                    "summary": "You have no meetings scheduled today.",
                    "meetings": [],
                    "conflicts": [],
                    "preparation": {}
                },
                "message": "No meetings for today",
                "error_code": None
            }

        #  Convert meeting times to datetime
        intervals = []
        meeting_map = {}

        for meeting in meetings:
            start = datetime.fromisoformat(
                meeting["start"].replace("Z", "")
            )
            end = datetime.fromisoformat(
                meeting["end"].replace("Z", "")
            )

            intervals.append((start, end))
            meeting_map[(start, end)] = meeting

        # Sort intervals chronologically
        intervals.sort(key=lambda x: x[0])

        #  Conflict Detection
        conflicts = []

        for i in range(len(intervals) - 1):
            if intervals[i][1] > intervals[i+1][0]:
                conflicts.append({
                    "first": meeting_map[intervals[i]]["title"],
                    "second": meeting_map[intervals[i+1]]["title"]
                })

        #  Preparation Suggestions
        preparation = {}

        for start, end in intervals:
            meeting = meeting_map[(start, end)]
            suggestions = []

            duration = (end - start).seconds // 60

            # Morning meeting heuristic
            if start.hour < 12:
                suggestions.append("Review notes before the meeting")

            # Long meeting heuristic
            if duration >= 60:
                suggestions.append("Prepare agenda points in advance")

            # Late afternoon fatigue heuristic
            if start.hour >= 15:
                suggestions.append("Keep buffer time before this meeting")

            preparation[meeting["id"]] = {
                "title": meeting["title"],
                "suggestions": suggestions
            }

        #  Create Summary
        summary = f"You have {len(intervals)} meetings today."

        if conflicts:
            summary += f" {len(conflicts)} scheduling conflict(s) detected."

        #  Worker Protocol Return
        return {
            "success": True,
            "data": {
                "summary": summary,
                "meetings": meetings,
                "conflicts": conflicts,
                "preparation": preparation
            },
            "message": "Daily briefing generated successfully",
            "error_code": None
        }

    except Exception as e:
        return {
            "success": False,
            "data": None,
            "message": str(e),
            "error_code": "AGENDA_ENGINE_ERROR"
        }
