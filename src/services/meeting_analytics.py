"""
meeting_analytics.py
--------------------
Feature 10: Meeting analytics computed from the local PostgreSQL DB.

Returns:
  - total meetings in period
  - average duration (minutes)
  - busiest day of the week
  - top 5 most frequent participants
  - count and rate of conflicting meetings
"""

from src.utils.db_handler import get_db_connection, release_db_connection


def get_meeting_analytics(user_email: str, from_date: str, to_date: str) -> dict:
    """
    Compute meeting analytics for a user over a date range.

    Parameters
    ----------
    user_email : str — organizer email to filter by
    from_date  : str — ISO date/datetime (inclusive start)
    to_date    : str — ISO date/datetime (inclusive end)
    """

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Total meetings + average duration
        cur.execute(
            """
            SELECT
                COUNT(*)                                                          AS total,
                AVG(EXTRACT(EPOCH FROM (end_time - start_time)) / 60.0)          AS avg_mins
            FROM meetings
            WHERE organizer_email = %s
              AND start_time BETWEEN %s AND %s;
            """,
            (user_email, from_date, to_date),
        )
        stats_row = cur.fetchone()
        total    = int(stats_row["total"])    if stats_row else 0
        avg_mins = float(stats_row["avg_mins"] or 0) if stats_row else 0.0

        # Busiest day of the week
        cur.execute(
            """
            SELECT TO_CHAR(start_time, 'Dy') AS day_name, COUNT(*) AS cnt
            FROM meetings
            WHERE organizer_email = %s
              AND start_time BETWEEN %s AND %s
            GROUP BY day_name
            ORDER BY cnt DESC
            LIMIT 1;
            """,
            (user_email, from_date, to_date),
        )
        day_row     = cur.fetchone()
        busiest_day = day_row["day_name"] if day_row else None

        # Top 5 most frequent participants
        cur.execute(
            """
            SELECT mp.participant_email, COUNT(*) AS appearances
            FROM meetings m
            JOIN meeting_participants mp ON mp.meeting_id = m.id
            WHERE m.organizer_email = %s
              AND m.start_time BETWEEN %s AND %s
            GROUP BY mp.participant_email
            ORDER BY appearances DESC
            LIMIT 5;
            """,
            (user_email, from_date, to_date),
        )
        top_participants = [
            {"email": r["participant_email"], "appearances": int(r["appearances"])}
            for r in cur.fetchall()
        ]

        # Meetings that overlap with at least one other meeting (same organizer)
        cur.execute(
            """
            SELECT COUNT(DISTINCT m1.id) AS conflicts
            FROM meetings m1
            JOIN meetings m2
              ON m1.id != m2.id
             AND m1.organizer_email = m2.organizer_email
             AND m1.start_time < m2.end_time
             AND m1.end_time   > m2.start_time
            WHERE m1.organizer_email = %s
              AND m1.start_time BETWEEN %s AND %s;
            """,
            (user_email, from_date, to_date),
        )
        conflict_row   = cur.fetchone()
        conflict_count = int(conflict_row["conflicts"]) if conflict_row else 0
        conflict_rate  = round(conflict_count / total * 100, 1) if total > 0 else 0.0

        cur.close()

        return {
            "success": True,
            "data": {
                "total_meetings":        total,
                "avg_duration_minutes":  round(avg_mins, 1),
                "busiest_day_of_week":   busiest_day,
                "top_participants":      top_participants,
                "conflicting_meetings":  conflict_count,
                "conflict_rate_pct":     conflict_rate,
                "period": {"from": from_date, "to": to_date},
            },
            "message":    "Analytics computed successfully",
            "error_code": None,
        }

    except Exception as e:
        return {
            "success":    False,
            "data":       None,
            "message":    str(e),
            "error_code": "ANALYTICS_ERROR",
        }

    finally:
        if conn:
            release_db_connection(conn)
