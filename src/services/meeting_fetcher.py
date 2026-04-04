"""
meeting_fetcher.py
------------------
Meeting search (DB) and fetch (Google Calendar) engine for S.A.M.
"""

from typing import Dict, List, Any

import psycopg2
import psycopg2.extras

from src.utils.db_handler import get_db_connection, release_db_connection
from src.utils.google_auth import get_calendar_service


class MeetingFetcherError(Exception):
    pass


# ---------------------------------------------------------------------------
# DB search — used by search/filter UIs
# ---------------------------------------------------------------------------

def search_meetings(filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Complex SQL search across the local meetings database.

    filters dict keys (all optional):
        participants : list[str]  — fuzzy name match
        department   : str
        date_range   : (start_date, end_date)  — ISO date strings
        time_slot    : (slot_start, slot_end)  — ISO datetime strings
    """

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        query = """
            SELECT
                m.meeting_id,
                m.title,
                m.start_time,
                m.end_time,
                m.organizer_email,
                m.meet_link,
                json_agg(
                    DISTINCT jsonb_build_object(
                        'name',  mp.participant_name,
                        'email', mp.participant_email
                    )
                ) AS participants
            FROM meetings m
            JOIN meeting_participants mp ON mp.meeting_id = m.id
            JOIN faculty f              ON f.email = mp.participant_email
            WHERE 1=1
        """

        params: List[Any] = []

        if filters.get("participants"):
            query += " AND mp.participant_name ILIKE ANY(%s)"
            params.append([f"%{p}%" for p in filters["participants"]])

        if filters.get("department"):
            query += " AND f.department = %s"
            params.append(filters["department"])

        if filters.get("date_range"):
            start_date, end_date = filters["date_range"]
            query += " AND m.start_time BETWEEN %s AND %s"
            params.extend([start_date, end_date])

        if filters.get("time_slot"):
            slot_start, slot_end = filters["time_slot"]
            query += " AND NOT (m.end_time <= %s OR m.start_time >= %s)"
            params.extend([slot_start, slot_end])

        query += """
            GROUP BY m.meeting_id, m.title, m.start_time, m.end_time,
                     m.organizer_email, m.meet_link
            ORDER BY m.start_time ASC
        """

        cursor.execute(query, params)
        rows = cursor.fetchall()

        if not rows:
            return {
                "success": True,
                "data": [],
                "message": "No meetings found matching the given criteria.",
                "error_code": None,
            }

        meetings = [
            {
                "meeting_id": row["meeting_id"],
                "title": row["title"],
                "start_time": row["start_time"].isoformat(),
                "end_time": row["end_time"].isoformat(),
                "organizer": row["organizer_email"],
                "meet_link": row.get("meet_link"),
                "participants": row["participants"],
                "conflicts": [],
            }
            for row in rows
        ]

        return {
            "success": True,
            "data": meetings,
            "message": f"Found {len(meetings)} meeting(s).",
            "error_code": None,
        }

    except psycopg2.Error:
        return {
            "success": False,
            "data": None,
            "message": "Database error while searching meetings.",
            "error_code": "DB_QUERY_FAILED",
        }

    except Exception:
        return {
            "success": False,
            "data": None,
            "message": "Unexpected error while searching meetings.",
            "error_code": "MEETING_FETCHER_FAILURE",
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            release_db_connection(conn)


# ---------------------------------------------------------------------------
# Google Calendar fetch — used by smart_agenda_engine
# ---------------------------------------------------------------------------

def fetch_meetings(user_email: str, time_min: str, time_max: str) -> Dict[str, Any]:
    """
    Fetch a user's Google Calendar events within a time window.

    Parameters
    ----------
    user_email : str  — email used to look up stored OAuth credentials
    time_min   : str  — ISO 8601 datetime (e.g. "2026-04-04T00:00:00Z")
    time_max   : str  — ISO 8601 datetime (e.g. "2026-04-04T23:59:59Z")

    Returns worker-protocol dict:
        {
            "success": bool,
            "data": {"meetings": [...]},
            "message": str,
            "error_code": str | None
        }
    Each meeting in the list has keys:
        id, title, start, end, meet_link, attendees
    """

    try:
        service = get_calendar_service(user_email=user_email)

        result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        raw_events = result.get("items", [])

        meetings = []
        for event in raw_events:
            start = event.get("start", {})
            end = event.get("end", {})
            meetings.append({
                "id": event.get("id"),
                "title": event.get("summary", "(No Title)"),
                "start": start.get("dateTime") or start.get("date"),
                "end": end.get("dateTime") or end.get("date"),
                "meet_link": event.get("hangoutLink"),
                "attendees": [
                    {"email": a.get("email"), "name": a.get("displayName")}
                    for a in event.get("attendees", [])
                ],
            })

        return {
            "success": True,
            "data": {"meetings": meetings},
            "message": f"Fetched {len(meetings)} event(s) from Google Calendar.",
            "error_code": None,
        }

    except Exception as e:
        return {
            "success": False,
            "data": None,
            "message": str(e),
            "error_code": "CALENDAR_FETCH_ERROR",
        }
