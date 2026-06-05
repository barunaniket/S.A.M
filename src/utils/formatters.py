"""
formatters.py
-------------
Small Telegram-flavoured markdown helpers used by the read-path intents
(query_attendance_sheet, query_my_attendance, query_class_submissions,
list_open_assignments_for_faculty, list_class_roster).

Telegram's HTML parser supports <b>, <i>, <code>, <pre>, <a>. We stick
to those four tags so the same string renders cleanly in WhatsApp's
plain-text mode too (the WA orchestrator strips tags).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, List, Mapping, Sequence


def format_attendance_sheet(*, subject: str, batch: str | None,
                            class_date: date,
                            present: Sequence[Mapping],
                            absent: Sequence[Mapping]) -> str:
    """
    Faculty-facing summary for one (subject, batch, date). Lifts the same
    visual style used by attendance_mcq._send_results_to_faculty so the
    "live results" message and the "show me the sheet later" message look
    identical.
    """
    total = len(present) + len(absent)
    when = class_date.strftime("%a %d %b")
    header = (f"📊 <b>{subject}</b> attendance — "
              f"{batch or 'all batches'} · {when} "
              f"({total} student{'s' if total != 1 else ''})")
    if total == 0:
        return header + "\n<i>No records for that day.</i>"

    lines: List[str] = [header]
    if present:
        lines.append("\n<b>Present</b>")
        for r in present:
            score = r.get("score")
            extra = f" — {score}/5" if score is not None else ""
            mark = " ⚙" if r.get("overridden") else ""
            lines.append(f"  ✓ {r.get('full_name') or 'Unknown'}{extra}{mark}")
    if absent:
        lines.append("\n<b>Absent</b>")
        for r in absent:
            mark = " ⚙" if r.get("overridden") else ""
            lines.append(f"  ✗ {r.get('full_name') or 'Unknown'}{mark}")
    return "\n".join(lines)


def format_my_attendance(*, student_name: str,
                         summary: Sequence[Mapping]) -> str:
    """
    Per-subject summary for one student.
    Each row in `summary`: {subject, present, total, percent}.
    """
    if not summary:
        return (f"<b>{student_name}</b>, no attendance records on file yet — "
                "you'll see your % once your faculty marks the first class.")

    lines: List[str] = [f"📈 <b>{student_name}</b> — attendance summary"]
    for row in summary:
        pct = row["percent"]
        bar = _pct_bar(pct)
        lines.append(
            f"  • <b>{row['subject']}</b> — {bar} {row['present']}/{row['total']} "
            f"({pct:.0f}%)"
        )
    overall = _overall_pct(summary)
    if overall is not None:
        lines.append(f"\n<i>Overall: {overall:.0f}%</i>")
    return "\n".join(lines)


def format_submissions(*, assignment_title: str, subject: str,
                       batch: str, due_at: datetime | None,
                       submitted: Sequence[Mapping],
                       missing: Sequence[Mapping]) -> str:
    when = ""
    if due_at:
        when = f" · due {due_at.strftime('%a %d %b %H:%M')}"
    header = (f"📥 <b>{subject} — {assignment_title}</b>\n"
              f"<i>{batch}{when}</i>")

    lines = [header,
             f"\n<b>Submitted</b> ({len(submitted)})"]
    if submitted:
        for r in submitted:
            stamp = r.get("submitted_at")
            stamp_s = stamp.strftime("%d %b %H:%M") if stamp else "—"
            lines.append(f"  ✓ {r.get('full_name')} · {stamp_s}")
    else:
        lines.append("  <i>nobody yet</i>")

    lines.append(f"\n<b>Missing</b> ({len(missing)})")
    if missing:
        for r in missing:
            lines.append(f"  ✗ {r.get('full_name')}")
    else:
        lines.append("  <i>everyone has submitted 🎉</i>")

    return "\n".join(lines)


def format_open_assignments(*, faculty_name: str,
                            rows: Sequence[Mapping]) -> str:
    if not rows:
        return (f"<b>{faculty_name}</b>, no open assignments. "
                "Say <i>create assignment for &lt;batch&gt;</i> to publish one.")
    lines = [f"📚 <b>Your open assignments</b> ({len(rows)})"]
    for r in rows:
        due = r.get("due_at")
        due_s = f" · due {due.strftime('%d %b %H:%M')}" if due else ""
        lines.append(
            f"  • <b>{r['subject']} — {r['title']}</b> "
            f"<i>({r['batch']}){due_s}</i> — "
            f"{r['submitted']}/{r['enrolled']} submitted"
        )
    return "\n".join(lines)


def format_class_roster(*, batch: str, rows: Sequence[Mapping]) -> str:
    if not rows:
        return (f"No students enrolled in <b>{batch}</b> yet. "
                "Run <code>python scripts/load_rosters.py</code> to seed.")
    lines = [f"👥 <b>{batch}</b> — {len(rows)} student(s)"]
    for r in rows:
        paired = "📱" if r.get("telegram_chat_id") else "·"
        last = r.get("last_seen")
        last_s = (f" · last marked {last.strftime('%d %b')}"
                  if isinstance(last, (date, datetime)) else "")
        lines.append(f"  {paired} {r.get('full_name')}{last_s}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _pct_bar(pct: float) -> str:
    """A 5-cell progress bar, 0 → ▱▱▱▱▱, 100 → ▰▰▰▰▰."""
    filled = max(0, min(5, round(pct / 20)))
    return "▰" * filled + "▱" * (5 - filled)


def _overall_pct(summary: Iterable[Mapping]) -> float | None:
    p = sum(int(r.get("present") or 0) for r in summary)
    t = sum(int(r.get("total") or 0) for r in summary)
    if t == 0:
        return None
    return 100.0 * p / t
