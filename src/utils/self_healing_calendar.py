"""
Self-healing calendar sync engine for S.A.M.

Detects external Google Calendar changes and keeps
the local PostgreSQL database in sync.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from src.utils.google_auth import get_calendar_service
from src.utils.db_handler import get_connection

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
        # TODO: fetch local DB rows
        # -------------------------
        local_events = {}

        # -------------------------
        # TODO: diff & detect changes
        # -------------------------
        created = updated = deleted = 0
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
