"""
self_healing_calendar.py
------------------------
Detects external Google Calendar changes and keeps the local PostgreSQL DB in sync.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from src.utils.google_auth import get_calendar_service
from src.utils.db_handler import get_db_connection, release_db_connection

logger = logging.getLogger(__name__)


def _fetch_remote_events(service, calendar_id: str, lookback_minutes: int):
    """Fetch events updated in the last `lookback_minutes` minutes, including deleted ones."""
    updated_min = (
        datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    ).isoformat()

    events = []
    page_token = None

    while True:
        response = service.events().list(
            calendarId=calendar_id,
            updatedMin=updated_min,
            showDeleted=True,
            singleEvents=True,
            pageToken=page_token,
        ).execute()

        events.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return events


def _fetch_local_events(conn, lookback_minutes: int) -> dict:
    """Fetch recently-touched meetings from local DB, indexed by Google event ID."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT *
        FROM meetings
        WHERE created_at >= NOW() - (%s || ' minutes')::interval;
        """,
        (lookback_minutes,),
    )
    rows = cursor.fetchall()
    cursor.close()
    return {row["meeting_id"]: row for row in rows}


def _diff_events(remote_events: list, local_events: dict) -> dict:
    """Compare Google events against DB records and return create/update/delete lists."""
    to_create, to_update, to_delete = [], [], []

    for event in remote_events:
        event_id = event.get("id")
        if not event_id:
            continue

        db_row = local_events.get(event_id)

        if event.get("status") == "cancelled":
            if db_row:
                to_delete.append(db_row)
            continue

        title = event.get("summary", "")
        start = event.get("start", {}).get("dateTime")
        end = event.get("end", {}).get("dateTime")
        meet_link = event.get("hangoutLink")
        organizer = event.get("organizer", {}).get("email")

        if not db_row:
            to_create.append(event)
            continue

        changed = (
            title != db_row.get("title")
            or (start and db_row["start_time"].isoformat() != start)
            or (end and db_row["end_time"].isoformat() != end)
            or meet_link != db_row.get("meet_link")
            or organizer != db_row.get("organizer_email")
        )

        if changed:
            to_update.append(event)

    return {"create": to_create, "update": to_update, "delete": to_delete}


def _log_activity(cursor, action_type: str, meeting_id, details: str):
    cursor.execute(
        "INSERT INTO activity_log (action_type, meeting_id, details) VALUES (%s, %s, %s);",
        (action_type, meeting_id, details),
    )


def _apply_creates(conn, events: list):
    cursor = conn.cursor()
    for event in events:
        cursor.execute(
            """
            INSERT INTO meetings (meeting_id, title, start_time, end_time, organizer_email, meet_link)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                event.get("id"),
                event.get("summary"),
                event["start"]["dateTime"],
                event["end"]["dateTime"],
                event.get("organizer", {}).get("email"),
                event.get("hangoutLink"),
            ),
        )
        meeting_pk = cursor.fetchone()[0]

        for attendee in event.get("attendees", []):
            cursor.execute(
                """
                INSERT INTO meeting_participants (meeting_id, participant_name, participant_email)
                VALUES (%s, %s, %s);
                """,
                (meeting_pk, attendee.get("displayName"), attendee.get("email")),
            )

        _log_activity(cursor, "CREATE", meeting_pk, f"Synced from Google event {event.get('id')}")
    cursor.close()


def _apply_updates(conn, events: list):
    cursor = conn.cursor()
    for event in events:
        cursor.execute(
            """
            UPDATE meetings
            SET title=%s, start_time=%s, end_time=%s, organizer_email=%s, meet_link=%s
            WHERE meeting_id=%s
            RETURNING id;
            """,
            (
                event.get("summary"),
                event["start"]["dateTime"],
                event["end"]["dateTime"],
                event.get("organizer", {}).get("email"),
                event.get("hangoutLink"),
                event.get("id"),
            ),
        )
        row = cursor.fetchone()
        if not row:
            continue

        meeting_pk = row[0]
        cursor.execute("DELETE FROM meeting_participants WHERE meeting_id=%s;", (meeting_pk,))

        for attendee in event.get("attendees", []):
            cursor.execute(
                """
                INSERT INTO meeting_participants (meeting_id, participant_name, participant_email)
                VALUES (%s, %s, %s);
                """,
                (meeting_pk, attendee.get("displayName"), attendee.get("email")),
            )

        _log_activity(cursor, "UPDATE", meeting_pk, f"Updated from Google event {event.get('id')}")
    cursor.close()


def _apply_deletes(conn, rows: list):
    cursor = conn.cursor()
    for row in rows:
        cursor.execute("DELETE FROM meetings WHERE id=%s;", (row["id"],))
        _log_activity(cursor, "DELETE", row["id"], "Deleted due to cancellation in Google Calendar")
    cursor.close()


def sync_calendar_changes(
    user_email: str,
    calendar_id: str = "primary",
    lookback_minutes: int = 120,
) -> Dict[str, Any]:
    """
    Sync recent Google Calendar changes into local DB.

    Parameters
    ----------
    user_email       : str  — whose calendar to sync (for OAuth credential lookup)
    calendar_id      : str  — Google Calendar ID (default "primary")
    lookback_minutes : int  — how far back to look for changes
    """

    logger.info("Starting calendar sync for %s (lookback=%s min)", user_email, lookback_minutes)

    conn = None
    try:
        service = get_calendar_service(user_email=user_email)
        remote_events = _fetch_remote_events(service, calendar_id, lookback_minutes)

        conn = get_db_connection()
        local_events = _fetch_local_events(conn, lookback_minutes)

        diff = _diff_events(remote_events, local_events)

        _apply_creates(conn, diff["create"])
        _apply_updates(conn, diff["update"])
        _apply_deletes(conn, diff["delete"])

        conn.commit()

        return {
            "success": True,
            "data": {
                "checked": len(remote_events),
                "created": len(diff["create"]),
                "updated": len(diff["update"]),
                "deleted": len(diff["delete"]),
            },
            "message": "Calendar sync completed",
            "error_code": None,
        }

    except Exception as exc:
        logger.exception("Calendar sync failed")
        if conn:
            conn.rollback()
        return {
            "success": False,
            "data": {},
            "message": "Calendar sync failed",
            "error_code": str(exc),
        }

    finally:
        if conn:
            release_db_connection(conn)
