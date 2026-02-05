"""
Self-healing calendar sync engine for S.A.M.

Detects external Google Calendar changes and keeps
the local PostgreSQL database in sync.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from src.utils.google_auth import get_calendar_service
from src.utils.db_handler import get_db_connection

logger = logging.getLogger(__name__)


def _fetch_remote_events(service, calendar_id: str, lookback_minutes: int):
    """
    Fetch events updated in the last `lookback_minutes` minutes,
    including deleted ones.
    """

    updated_min = (
        datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    ).isoformat()

    events = []
    page_token = None

    while True:
        request = service.events().list(
            calendarId=calendar_id,
            updatedMin=updated_min,
            showDeleted=True,
            singleEvents=True,
            pageToken=page_token,
        )

        response = request.execute()
        events.extend(response.get("items", []))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return events

def _fetch_local_events(conn, lookback_minutes: int):
    """
    Fetch meetings updated recently from local DB.

    Returns dict indexed by google_event_id.
    """

    cursor = conn.cursor()

    query = """
        SELECT *
        FROM meetings
        WHERE updated_at >= NOW() - (%s || ' minutes')::interval;
    """

    cursor.execute(query, (lookback_minutes,))
    rows = cursor.fetchall()

    cursor.close()

    return {row["google_event_id"]: row for row in rows}

def _diff_events(remote_events, local_events):
    """
    Compare Google events vs DB records.

    Returns dict with create / update / delete lists.
    """

    to_create = []
    to_update = []
    to_delete = []

    for event in remote_events:
        event_id = event.get("id")
        status = event.get("status")

        if not event_id:
            continue

        db_row = local_events.get(event_id)

        # ---- Cancelled remotely ----
        if status == "cancelled":
            if db_row:
                to_delete.append(db_row)
            continue

        title = event.get("summary", "")
        start = event.get("start", {}).get("dateTime")
        end = event.get("end", {}).get("dateTime")
        meet_link = event.get("hangoutLink")
        organizer = event.get("organizer", {}).get("email")

        # ---- New meeting ----
        if not db_row:
            to_create.append(event)
            continue

        # ---- Compare for updates ----
        changed = False

        if title != db_row["title"]:
            changed = True

        if start and db_row["start_time"].isoformat() != start:
            changed = True

        if end and db_row["end_time"].isoformat() != end:
            changed = True

        if meet_link != db_row["meet_link"]:
            changed = True

        if organizer != db_row["organizer_email"]:
            changed = True

        if changed:
            to_update.append(event)

    return {
        "create": to_create,
        "update": to_update,
        "delete": to_delete,
    }


def sync_calendar_changes(
    calendar_id: str = "primary",
    lookback_minutes: int = 120,
) -> Dict[str, Any]:
    """
    Sync recent Google Calendar changes into local DB.

    Returns:
        {
            "success": bool,
            "data": {
                "checked": int,
                "updated": int,
                "deleted": int,
                "created": int,
            },
            "message": str,
            "error_code": str | None,
        }
    """

    logger.info(
        "Starting self-healing calendar sync (calendar_id=%s, lookback=%s)",
        calendar_id,
        lookback_minutes,
    )

    try:
        # -------------------------
        # Fetch remote events
        # -------------------------
        service = get_calendar_service()
        remote_events = _fetch_remote_events(
            service, calendar_id, lookback_minutes
        )

        # -------------------------
        # Fetch local DB rows
        # -------------------------
        conn = get_db_connection()
        local_events = _fetch_local_events(conn, lookback_minutes)

        # -------------------------
        # TODO: diff & detect changes
        # -------------------------
        diff = _diff_events(remote_events, local_events)

        created = len(diff["create"])
        updated = len(diff["update"])
        deleted = len(diff["delete"])
        checked = len(remote_events)

        # -------------------------
        # TODO: apply DB updates
        # -------------------------

        result = {
            "success": True,
            "data": {
                "checked": checked,
                "updated": updated,
                "deleted": deleted,
                "created": created,
            },
            "message": "Calendar sync completed",
            "error_code": None,
        }

        return result

    except Exception as exc:
        logger.exception("Self-healing calendar sync failed")

        return {
            "success": False,
            "data": {},
            "message": "Calendar sync failed",
            "error_code": str(exc),
        }
