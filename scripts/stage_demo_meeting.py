"""
Schedule a real meeting at NOW + offset-min so the 10-min reminder fires
on stage during the demo. Default offset is 13 minutes — enough for the
broadcast to land first, then the 10-min Celery reminder ~3 min later.

Defaults (override via flags):
  - participants:  Dr Sharma + Prof Kumar (the seeded demo faculty)
  - scheduler:     the SPOC seeded by scripts/seed_demo.py
  - title:         "Exam review prep"
  - duration:      30 minutes

Examples:
    python scripts/stage_demo_meeting.py
    python scripts/stage_demo_meeting.py --title "Mid-sem moderation"
    python scripts/stage_demo_meeting.py --offset-min 8 --duration-min 20
    python scripts/stage_demo_meeting.py --no-calendar
    python scripts/stage_demo_meeting.py --participants "Dr Priya Sharma" "Meera Iyer"

`--no-calendar` skips the Google Calendar write and goes through
`meeting_lite.create_meeting_lite` instead — useful when Google is down on
demo-day or the SPOC's OAuth tokens haven't been provisioned. Email + ICS +
WhatsApp + Telegram broadcasts and the 10-min reminder all still fire.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.config_loader import Config  # noqa: F401  -- ensures .env is loaded
from src.utils.db_handler import (
    get_db_connection,
    get_user_by_email,
    release_db_connection,
)


DEFAULT_PARTICIPANTS = ["Dr Priya Sharma", "Prof Rahul Kumar"]
DEFAULT_TITLE = "Exam review prep"
DEFAULT_OFFSET_MIN = 13       # meeting starts NOW+13min
DEFAULT_DURATION_MIN = 30
DEFAULT_LOCATION = "Faculty Block, Conference Room"


def _spoc_email() -> str:
    return os.getenv("DEMO_SPOC_EMAIL", "spoc@example.edu")


def _resolve_attendees(names):
    """For --no-calendar path: turn display names into attendee dicts."""
    out = []
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        for n in names:
            cur.execute(
                """
                SELECT id, email, full_name AS name, phone_number AS phone,
                       telegram_chat_id, role, department
                  FROM users
                 WHERE LOWER(full_name) LIKE LOWER(%s)
                 LIMIT 1;
                """,
                (f"%{n}%",),
            )
            row = cur.fetchone()
            if row:
                out.append(dict(row))
            else:
                print(f"  ! could not resolve participant '{n}' — skipping")
        cur.close()
    finally:
        release_db_connection(conn)
    return out


def _print_banner(label: str, value: str) -> None:
    print(f"  {label:<14} {value}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--offset-min", type=int, default=DEFAULT_OFFSET_MIN,
                        help="Minutes from now until the meeting starts (default: 13)")
    parser.add_argument("--duration-min", type=int, default=DEFAULT_DURATION_MIN,
                        help="Meeting length in minutes (default: 30)")
    parser.add_argument("--participants", nargs="+", default=DEFAULT_PARTICIPANTS,
                        help="Faculty display names to invite")
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--agenda", default=None,
                        help="Optional meeting agenda string")
    parser.add_argument("--no-calendar", action="store_true",
                        help="Skip Google Calendar; use meeting_lite path "
                             "(email + ICS + WhatsApp/Telegram + reminders only)")
    args = parser.parse_args()

    if args.offset_min < 11 and not args.no_calendar:
        print("  ! offset-min < 11: the 10-minute reminder will NOT fire "
              "(eta would be in the past). Bumping to 13.")
        args.offset_min = 13

    start_dt = datetime.now() + timedelta(minutes=args.offset_min)
    end_dt   = start_dt + timedelta(minutes=args.duration_min)
    start_iso = start_dt.replace(microsecond=0).isoformat()
    end_iso   = end_dt.replace(microsecond=0).isoformat()

    spoc_email = _spoc_email()
    spoc = get_user_by_email(spoc_email)
    if not spoc:
        print(f"❌ SPOC user '{spoc_email}' not found. Did you run seed_demo.py?")
        sys.exit(1)

    print()
    print("──────── stage-meeting ────────")
    _print_banner("Title:",        args.title)
    _print_banner("Starts:",       f"{start_iso}  ({args.offset_min} min from now)")
    _print_banner("Ends:",         end_iso)
    _print_banner("Duration:",     f"{args.duration_min} minutes")
    _print_banner("Location:",     args.location)
    _print_banner("Scheduler:",    f"{spoc.get('full_name')} <{spoc_email}>")
    _print_banner("Participants:", ", ".join(args.participants))
    _print_banner("Mode:",         "calendar-skipped (lite)" if args.no_calendar else "real (Google Calendar)")
    print()

    # Approximate when the 10-min reminder will fire — useful for the
    # demo timer.
    reminder_eta = start_dt - timedelta(minutes=10)
    if reminder_eta > datetime.now():
        secs = int((reminder_eta - datetime.now()).total_seconds())
        print(f"  → 10-min reminder fires in ~{secs}s (at {reminder_eta.strftime('%H:%M:%S')})")

    if args.no_calendar:
        from src.services.meeting_lite import create_meeting_lite

        attendees = _resolve_attendees(args.participants)
        if not attendees:
            print("❌ no attendees resolved — aborting")
            sys.exit(1)

        result = create_meeting_lite(
            org_id=spoc["org_id"],
            organizer_id=spoc["id"],
            organizer_name=spoc.get("full_name"),
            organizer_email=spoc_email,
            title=args.title,
            start_time=start_iso,
            end_time=end_iso,
            attendees=attendees,
            location=args.location,
            agenda=args.agenda,
        )
    else:
        from src.services.meeting_creator import create_meeting

        result = create_meeting(
            title=args.title,
            start_datetime=start_iso,
            end_datetime=end_iso,
            participant_names=args.participants,
            scheduler_email=spoc_email,
            org_id=spoc["org_id"],
        )

    print()
    if result.get("success"):
        print(f"  ✓ {result.get('message') or 'meeting scheduled'}")
        if result.get("meeting_id"):
            _print_banner("meeting_id:", str(result["meeting_id"]))
        if result.get("ics_path"):
            _print_banner("ics:", result["ics_path"])
        if result.get("counts"):
            _print_banner("delivered:", str(result["counts"]))
        if result.get("event_id"):
            _print_banner("calendar_id:", result["event_id"])
    else:
        print(f"  ✗ stage-meeting reported failure")
        for k, v in result.items():
            print(f"     {k}: {v}")
        if not args.no_calendar:
            print()
            print("  💡 Try --no-calendar if Google OAuth isn't ready:")
            print("     ./demo.sh stage-meeting --no-calendar")


if __name__ == "__main__":
    main()
