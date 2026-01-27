import logging
import uuid
from datetime import datetime
from pathlib import Path

import pytz
from icalendar import Calendar, Event


logger = logging.getLogger(__name__)


def generate_ics(
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    organizer: dict,
    attendees: list,
    output_dir: str = "data/ics",
) -> str:
    """
    Generate an ICS file for a meeting.

    Args:
        title (str): Meeting title/subject.
        start_dt (datetime): Timezone-aware start datetime.
        end_dt (datetime): Timezone-aware end datetime.
        organizer (dict): {"name": str, "email": str}
        attendees (list): List of {"name": str, "email": str}
        output_dir (str): Directory to store ICS files.

    Returns:
        str: Path to the generated .ics file.
    """

    # -------------------------------
    # Validation
    # -------------------------------
    if start_dt.tzinfo is None or end_dt.tzinfo is None:
        raise ValueError("start_dt and end_dt must be timezone-aware datetimes")

    if start_dt >= end_dt:
        raise ValueError("start_dt must be before end_dt")

    # -------------------------------
    # Calendar container
    # -------------------------------
    cal = Calendar()
    cal.add("prodid", "-//S.A.M//Meeting Scheduler//EN")
    cal.add("version", "2.0")

    # -------------------------------
    # Event
    # -------------------------------
    event = Event()
    event.add("uid", f"{uuid.uuid4()}@sam")
    event.add("summary", title)

    event.add("dtstart", start_dt)
    event.add("dtend", end_dt)
    event.add("dtstamp", datetime.now(pytz.UTC))

    # -------------------------------
    # Organizer
    # -------------------------------
    event.add(
        "organizer",
        f"MAILTO:{organizer['email']}",
        parameters={"CN": organizer["name"]},
    )

    # -------------------------------
    # Attendees
    # -------------------------------
    for person in attendees:
        event.add(
            "attendee",
            f"MAILTO:{person['email']}",
            parameters={
                "CN": person["name"],
                "ROLE": "REQ-PARTICIPANT",
            },
        )

    cal.add_component(event)

    # -------------------------------
    # Save to disk
    # -------------------------------
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    file_path = output_path / f"{uuid.uuid4()}.ics"

    with open(file_path, "wb") as f:
        f.write(cal.to_ical())

    logger.info("ICS file generated at %s", file_path)

    return str(file_path)
