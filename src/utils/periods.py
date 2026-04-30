"""
periods.py
----------
Class-period helpers for the period-aware "where will Prof X be during
4th period?" lookup.

The mapping is hardcoded for the 2-day demo. For production, lift the
table into an `org_periods` row so each institution can configure its
own bell schedule.

Default schedule used here is the standard 8-period day with a 1-hour
lunch between 4th and 5th periods (matches most CSE/ECE timetables in
Indian engineering colleges).
"""

from datetime import date, datetime, time, timedelta
from typing import Dict, Optional, Tuple


# Period -> (start, end). 50-minute slots, 10-min change-over.
DEFAULT_PERIODS: Dict[int, Tuple[time, time]] = {
    1: (time(9, 0),  time(9, 50)),
    2: (time(10, 0), time(10, 50)),
    3: (time(11, 0), time(11, 50)),
    4: (time(12, 0), time(12, 50)),    # lunch break after this
    5: (time(14, 0), time(14, 50)),
    6: (time(15, 0), time(15, 50)),
    7: (time(16, 0), time(16, 50)),
    8: (time(17, 0), time(17, 50)),
}


def period_window(period_num: int, on: Optional[date] = None) -> Optional[Tuple[datetime, datetime]]:
    """
    Resolve `period_num` (1-8) to a (start_dt, end_dt) on the given day
    (defaults to today). Returns None if the number is out of range.
    """
    slot = DEFAULT_PERIODS.get(int(period_num))
    if not slot:
        return None
    when = on or date.today()
    start = datetime.combine(when, slot[0])
    end = datetime.combine(when, slot[1])
    return start, end


def format_period(period_num: int) -> str:
    """1 → '1st', 2 → '2nd', 3 → '3rd', 4 → '4th', …"""
    n = int(period_num)
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def period_label(period_num: int) -> str:
    """E.g. '4th period (12:00-12:50)'."""
    win = period_window(period_num)
    if not win:
        return f"period {period_num}"
    start, end = win
    return (f"{format_period(period_num)} period "
            f"({start.strftime('%H:%M')}-{end.strftime('%H:%M')})")


def parse_day_keyword(keyword: Optional[str]) -> Optional[date]:
    """
    Map a natural-language day reference to a concrete date.
    Returns None if the keyword is empty/unrecognised — caller defaults to today.
    """
    if not keyword:
        return None
    k = keyword.strip().lower()
    today = date.today()
    if k in ("today", "now"):
        return today
    if k == "tomorrow":
        return today + timedelta(days=1)
    if k == "yesterday":
        return today - timedelta(days=1)
    weekdays = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tue": 1, "tues": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6,
    }
    if k in weekdays:
        target = weekdays[k]
        delta = (target - today.weekday()) % 7
        # If today is the named weekday, "monday" means *this* monday (today),
        # not next week. Caller can pass "next monday" -> still same logic.
        return today + timedelta(days=delta)
    return None
