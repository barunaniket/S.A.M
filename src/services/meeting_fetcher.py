"""
meeting_fetcher.py
------------------
Advanced meeting search and availability query engine for S.A.M (Phase 2).

Owner: Krishna H Zalavadiya (Data Engineer)

Responsibilities:
- Perform complex SQL searches on meetings
- Support multi-dimensional filters
- Return LLM-safe structured responses
- Maintain high performance and reliability
"""

from typing import Dict, List, Any
import psycopg2
import psycopg2.extras

from utils.db_handler import get_db_connection


class MeetingFetcherError(Exception):
    """Base exception for meeting fetcher errors."""
    pass


def search_meetings(filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Complex SQL search across meetings database.

    Parameters
    ----------
    filters : dict
        {
            "participants": ["Aniket"],
            "department": "AIML",
            "date_range": ("2026-02-01", "2026-02-07"),
            "time_slot": ("09:00", "17:00")
        }

    Returns
    -------
    dict
        Standardized worker response:
        {
            "success": bool,
            "data": list,
            "message": str,
            "error_code": str | None
        }
    """

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # -------------------------------
        # Base query (optimized JOINs)
        # -------------------------------
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
                        'name', mp.participant_name,
                        'email', mp.participant_email
                    )
                ) AS participants
            FROM meetings m
            JOIN meeting_participants mp
                ON mp.meeting_id = m.id
            JOIN faculty f
                ON f.email = mp.participant_email
            WHERE 1=1
        """

        params: List[Any] = []

        # -------------------------------
        # Dynamic filters
        # -------------------------------

        # Participant name filter (ILIKE for fuzzy matching)
        if filters.get("participants"):
            query += " AND mp.participant_name ILIKE ANY(%s)"
            params.append([f"%{p}%" for p in filters["participants"]])

        # Department filter
        if filters.get("department"):
            query += " AND f.department = %s"
            params.append(filters["department"])

        # Date range filter
        if filters.get("date_range"):
            start_date, end_date = filters["date_range"]
            query += " AND m.start_time BETWEEN %s AND %s"
            params.extend([start_date, end_date])

        # Time slot overlap filter (correct overlap logic)
        if filters.get("time_slot"):
            slot_start, slot_end = filters["time_slot"]
            query += """
                AND NOT (
                    m.end_time <= %s
                    OR m.start_time >= %s
                )
            """
            params.extend([slot_start, slot_end])

        # -------------------------------
        # Grouping & ordering
        # -------------------------------
        query += """
            GROUP BY
                m.meeting_id,
                m.title,
                m.start_time,
                m.end_time,
                m.organizer_email,
                m.meet_link
            ORDER BY m.start_time ASC
        """

        # -------------------------------
        # Execute query
        # -------------------------------
        cursor.execute(query, params)
        rows = cursor.fetchall()

        if not rows:
            return {
                "success": True,
                "data": [],
                "message": "No meetings found matching the given criteria.",
                "error_code": None
            }

        # -------------------------------
        # Normalize output
        # -------------------------------
        meetings = []
        for row in rows:
            meetings.append({
                "meeting_id": row["meeting_id"],
                "title": row["title"],
                "start_time": row["start_time"].isoformat(),
                "end_time": row["end_time"].isoformat(),
                "organizer": row["organizer_email"],
                "meet_link": row.get("meet_link"),
                "participants": row["participants"],
                "conflicts": []  # Reserved for future intelligence layer
            })

        return {
            "success": True,
            "data": meetings,
            "message": f"Found {len(meetings)} meeting(s).",
            "error_code": None
        }

    except psycopg2.Error as db_error:
        return {
            "success": False,
            "data": None,
            "message": "Database error occurred while searching meetings.",
            "error_code": "DB_QUERY_FAILED"
        }

    except Exception as exc:
        return {
            "success": False,
            "data": None,
            "message": "Unexpected error occurred while searching meetings.",
            "error_code": "MEETING_FETCHER_FAILURE"
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
