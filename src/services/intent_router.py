"""
intent_router.py
----------------
Feature 1: End-to-end NLP orchestrator.

Receives a parsed intent dict from LLMProcessor and executes the corresponding
service call, returning a unified response. Used by POST /api/v1/process/execute
and by the WhatsApp orchestrator.

Supported intents:
    create_meeting, reschedule_meeting, cancel_meeting,
    list_meetings, send_email,
    broadcast_notification, create_group, list_groups,
    confirm_upload, discard_upload,
    onboard_timetable, confirm_timetable, discard_timetable,
    query_faculty_status,
    cancel_class,
    start_mcq_attendance, start_poll_attendance, close_poll,
    override_attendance,
    query_my_next_class,
    query_attendance_sheet, query_my_attendance,
    query_class_submissions, list_open_assignments_for_faculty,
    list_class_roster,
    clarification_needed
"""

import logging
from datetime import datetime

from src.services.broadcast_service import broadcast_by_filters
from src.services.direct_email_service import DirectEmailService
from src.services.group_service import (
    add_members_by_email,
    create_group,
    list_groups,
)
from src.services.meeting_creator import create_meeting
from src.services.meeting_fetcher import search_meetings
from src.services.meeting_modifier import cancel_meeting, reschedule_meeting

logger = logging.getLogger(__name__)


def _format_status_with_cabin(*, faculty: dict, entry: dict | None,
                              when_label: str) -> str:
    """
    Compose the response for query_faculty_status. If the faculty has a
    timetable entry overlapping `when_label`, surface the class + room.
    Otherwise fall back to their `office_location` ("should be in her
    cabin"), which is the most useful answer for a student trying to
    reach them between classes.
    """
    name = faculty.get("full_name") or "They"
    pronoun = "they"
    role = (faculty.get("role") or "").upper()
    if role in ("FACULTY", "ADMIN", "SUPER_ADMIN"):
        # We don't track gender; "they" is the safe default. Callers who
        # know better can override on the UI side.
        pronoun = "they"

    if entry:
        parts = [f"{name} is in"]
        if entry.get("subject"):
            parts.append(f" {entry['subject']}")
        if entry.get("room"):
            parts.append(f" at {entry['room']}")
        if entry.get("batch"):
            parts.append(f" with {entry['batch']}")
        parts.append(
            f" ({entry['start_time']}–{entry['end_time']}) {when_label}."
        )
        cabin = faculty.get("office_location")
        if cabin:
            parts.append(f" After that, try {cabin}.")
        return "".join(parts)

    cabin = faculty.get("office_location")
    if cabin:
        return (f"{name} doesn't have a class {when_label} — "
                f"{pronoun} should be in {cabin}.")
    return (f"{name} doesn't have a class scheduled {when_label}. "
            f"No office location on file — try email or WhatsApp.")


def route_intent(intent_result: dict, scheduler_email: str,
                 org_id: int = None) -> dict:
    """
    Route a parsed intent to the appropriate service and return its result.

    Parameters
    ----------
    intent_result   : dict returned by LLMProcessor.process_user_intent()
    scheduler_email : authenticated user's email from JWT (organiser)
    org_id          : tenant id (required for broadcast_notification);
                      callers from JWT-authed routes should pass request.state.org_id
    """

    intent   = intent_result.get("intent")
    entities = intent_result.get("entities", {}) or {}

    # ------------------------------------------------------------------
    if intent == "create_meeting":
        title = entities.get("title") or "Untitled Meeting"
        start = entities.get("start_time")
        end   = entities.get("end_time")

        if not start:
            return {
                "success":             False,
                "needs_clarification": True,
                "message":             "What time should the meeting start?",
            }

        # Default a missing end_time to start + 1h. People rarely say "3pm to
        # 4pm" out loud — "meet at 3pm" means a one-hour slot in practice.
        if not end:
            try:
                from datetime import timedelta as _td
                end_dt = datetime.fromisoformat(start.replace("Z", "")) + _td(hours=1)
                end = end_dt.isoformat()
            except ValueError:
                return {
                    "success":             False,
                    "needs_clarification": True,
                    "message":             "I couldn't parse the start time. Try '3pm' or '15:00'.",
                }

        return create_meeting(
            title=title,
            start_datetime=start,
            end_datetime=end,
            participant_names=entities.get("participants", []),
            scheduler_email=scheduler_email,
            org_id=org_id,
        )

    # ------------------------------------------------------------------
    elif intent == "reschedule_meeting":
        meeting_id = entities.get("target_meeting_id")
        if not meeting_id:
            return {
                "success":             False,
                "needs_clarification": True,
                "message":             "Please provide the meeting ID to reschedule.",
            }
        if not entities.get("start_time") or not entities.get("end_time"):
            return {
                "success":             False,
                "needs_clarification": True,
                "message":             "Please specify the new start and end time.",
            }
        return reschedule_meeting(
            meeting_id=meeting_id,
            new_start_datetime=entities["start_time"],
            new_end_datetime=entities["end_time"],
            scheduler_email=scheduler_email,
            org_id=org_id,
        )

    # ------------------------------------------------------------------
    elif intent == "cancel_meeting":
        meeting_id = entities.get("target_meeting_id")
        if not meeting_id:
            return {
                "success":             False,
                "needs_clarification": True,
                "message":             "Please provide the meeting ID to cancel.",
            }
        return cancel_meeting(
            meeting_id=meeting_id,
            scheduler_email=scheduler_email,
        )

    # ------------------------------------------------------------------
    elif intent == "list_meetings":
        filters = {}
        if entities.get("participants"):
            filters["participants"] = entities["participants"]
        return search_meetings(filters)

    # ------------------------------------------------------------------
    elif intent == "send_email":
        participants = entities.get("participants", [])
        target_name  = participants[0] if participants else ""
        if not target_name:
            return {
                "success":             False,
                "needs_clarification": True,
                "message":             "Who should I send the email to?",
            }
        svc = DirectEmailService()
        return svc.send_email(
            target_name=target_name,
            subject=entities.get("title") or "Message from S.A.M.",
            message_body=entities.get("body") or intent_result.get("message") or "",
        )

    # ------------------------------------------------------------------
    elif intent == "broadcast_notification":
        body = entities.get("body") or intent_result.get("message")
        if not body:
            return {
                "success":             False,
                "needs_clarification": True,
                "message":             "What message should I broadcast?",
            }
        if org_id is None:
            return {"success": False, "error": "broadcast requires org_id context."}
        return broadcast_by_filters(
            org_id=org_id,
            body=body,
            subject=entities.get("title") or "Update from your faculty",
            target_role=entities.get("target_role"),
            target_department=entities.get("target_department"),
            target_group_id=entities.get("target_group_id"),
            target_group_name=entities.get("target_group_name") or entities.get("group_name"),
            channels=entities.get("channels") or ["email", "whatsapp"],
        )

    # ------------------------------------------------------------------
    elif intent == "create_group":
        if org_id is None:
            return {"success": False, "error": "create_group requires org_id context."}
        name = entities.get("group_name") or entities.get("title")
        if not name:
            return {"success": False, "needs_clarification": True,
                    "message": "What should the group be called?"}
        result = create_group(
            org_id=org_id,
            name=name,
            description=entities.get("description"),
        )
        if result.get("success") and entities.get("members_emails"):
            add_members_by_email(
                org_id=org_id,
                group_id=result["data"]["id"],
                emails=entities["members_emails"],
            )
        if result.get("success"):
            result["message"] = (
                f"Group '{name}' is ready."
                if not result.get("already_exists")
                else f"Group '{name}' already exists — left unchanged."
            )
        return result

    # ------------------------------------------------------------------
    elif intent == "list_groups":
        if org_id is None:
            return {"success": False, "error": "list_groups requires org_id context."}
        groups = list_groups(org_id)
        if not groups:
            return {"success": True, "data": [], "message": "You have no groups yet."}
        names = ", ".join(f"{g['name']} ({g['member_count']})" for g in groups)
        return {"success": True, "data": groups, "message": f"Your groups: {names}."}

    # ------------------------------------------------------------------
    elif intent in ("confirm_upload", "discard_upload",
                    "onboard_timetable",
                    "confirm_timetable", "discard_timetable",
                    "assign_tasks", "confirm_tasks", "discard_tasks",
                    "create_assignment", "submit_assignment",
                    "list_my_assignments"):
        # (cancel_class is handled below — it can be answered by REST too,
        # because cancellation_service has all the context it needs.)
        # These are stateful flows handled by the WhatsApp orchestrator,
        # which holds the session + pending_upload context. If we land here
        # it means the caller is the REST router which doesn't have that
        # context.
        return {
            "success":             False,
            "needs_clarification": True,
            "message":             "Stateful conversational intents are handled "
                                   "by the WhatsApp orchestrator, not the REST router.",
        }

    # ------------------------------------------------------------------
    elif intent == "cancel_class":
        # FACULTY/ADMIN only — the orchestrator should already have gated
        # the inbound by role, but defend in depth.
        if org_id is None:
            return {"success": False, "error": "cancel_class requires org_id context."}
        from src.services.cancellation_service import cancel_class_today
        from src.utils.db_handler import get_user_by_email

        subject = entities.get("target_subject") or entities.get("title")
        if not subject:
            return {"success": False, "needs_clarification": True,
                    "message": "Which class do you want to cancel? "
                               "(e.g. 'cancel DSA today')"}

        faculty = get_user_by_email(scheduler_email) if scheduler_email else None
        if not faculty:
            return {"success": False,
                    "message": "I couldn't identify your account."}

        return cancel_class_today(
            org_id=org_id,
            faculty_id=faculty["id"],
            subject_query=subject,
            faculty_name=faculty.get("full_name"),
            reason=entities.get("body"),
        )

    elif intent == "query_faculty_status":
        # "Where is Prof Sharma now?" / "Is Prof Mehta free at 3?"
        # / "I want to contact Dr Iyer for mentoring during 4th period"
        # Resolves faculty name fuzzily, looks up timetable + active meeting
        # at the requested time. Available to STUDENT, FACULTY, ADMIN.
        if org_id is None:
            return {"success": False, "error": "query_faculty_status requires org_id context."}

        from src.services.timetable_service import (
            resolve_faculty_by_name,
            who_is_busy_at,
        )
        from src.utils.periods import (
            parse_day_keyword,
            period_label,
            period_window,
        )

        target = entities.get("target_faculty_name") or entities.get("title")
        if not target and entities.get("participants"):
            target = entities["participants"][0]
        if not target:
            return {"success": False, "needs_clarification": True,
                    "message": "Which faculty member are you asking about?"}

        candidates = resolve_faculty_by_name(org_id, target)
        if not candidates:
            return {"success": True,
                    "message": f"I couldn't find anyone matching \"{target}\". "
                               "Try the full name or department."}

        # Multi-hit disambiguation when top score is close to runner-up.
        if len(candidates) > 1 and (
            candidates[0]["score"] - candidates[1]["score"] < 6
        ):
            preview = ", ".join(
                f"{c['full_name']} ({c.get('department') or c['role']})"
                for c in candidates[:5]
            )
            return {"success": True, "needs_clarification": True,
                    "message": f"I found a few people matching \"{target}\": "
                               f"{preview}. Which one?"}

        faculty = candidates[0]

        # Resolve the time window the student is asking about. Three sources
        # in priority order:
        #   1. query_period (+ query_day_keyword) — bell-schedule-aware
        #   2. query_time   — explicit ISO 8601
        #   3. neither      — "right now"
        when_dt = None
        when_label = "right now"
        period_num = entities.get("query_period")
        day_keyword = entities.get("query_day_keyword")

        if period_num:
            target_day = parse_day_keyword(day_keyword)
            window = period_window(int(period_num), on=target_day)
            if window:
                when_dt = window[0]
                day_phrase = (day_keyword or "today").lower()
                when_label = f"during {period_label(int(period_num))} {day_phrase}"
        if when_dt is None:
            qt = entities.get("query_time")
            if qt:
                try:
                    when_dt = datetime.fromisoformat(qt.replace("Z", ""))
                    when_label = f"at {when_dt.strftime('%H:%M on %A')}"
                except ValueError:
                    when_dt = None

        entry = who_is_busy_at(faculty["id"], when_dt)
        msg = _format_status_with_cabin(
            faculty=faculty,
            entry=entry,
            when_label=when_label,
        )

        # Layer in active Google Calendar meetings (best-effort).
        try:
            mtgs = search_meetings({"participants": [faculty.get("email")]}) or {}
            data = mtgs.get("data") or []
            now = when_dt or datetime.now()
            active = []
            for m in data if isinstance(data, list) else []:
                start = m.get("start_time") or m.get("start")
                end = m.get("end_time") or m.get("end")
                if not start or not end:
                    continue
                try:
                    s = datetime.fromisoformat(str(start).replace("Z", ""))
                    e = datetime.fromisoformat(str(end).replace("Z", ""))
                except ValueError:
                    continue
                if s <= now < e:
                    active.append(m.get("title") or "a meeting")
            if active:
                msg += f" Also in a Calendar meeting: {active[0]}."
        except Exception:
            logger.debug("Calendar overlay failed for faculty status query", exc_info=True)

        return {"success": True, "data": {"faculty": faculty, "entry": entry},
                "message": msg}

    # ------------------------------------------------------------------
    elif intent == "start_mcq_attendance":
        # Faculty wants to take attendance via a 5-question MCQ quiz.
        if org_id is None or not scheduler_email:
            return {"success": False,
                    "error": "start_mcq_attendance requires the faculty session."}

        from src.services.attendance_mcq import start_session
        from src.services.timetable_service import who_is_busy_at
        from src.utils.db_handler import get_user_by_email

        faculty = get_user_by_email(scheduler_email)
        if not faculty:
            return {"success": False,
                    "message": "I couldn't resolve your faculty account."}
        if faculty.get("role") not in ("FACULTY", "ADMIN", "SUPER_ADMIN"):
            return {"success": False,
                    "message": "Only faculty/admin can start MCQ attendance."}

        subject = entities.get("target_subject") or entities.get("title")
        batch   = entities.get("target_batch")

        # Infer subject + batch from the faculty's current period if missing.
        if not subject or not batch:
            now_class = who_is_busy_at(faculty["id"])
            if now_class:
                subject = subject or now_class.get("subject")
                batch   = batch   or now_class.get("batch")

        if not subject:
            return {"success": False, "needs_clarification": True,
                    "message": "Which subject is this attendance for? "
                               "(e.g. 'start mcq attendance for DSA')"}
        if not batch:
            return {"success": False, "needs_clarification": True,
                    "message": "Which batch is this for? "
                               "(e.g. 'start mcq attendance for DSA in CSE-3A')"}

        result = start_session(faculty=faculty, batch=batch, subject=subject)
        return result

    # ------------------------------------------------------------------
    elif intent == "start_poll_attendance":
        # Faculty wants the simple "I'm here" tap flow.
        if org_id is None or not scheduler_email:
            return {"success": False,
                    "error": "start_poll_attendance requires the faculty session."}

        from src.services.attendance_poll import start_session
        from src.services.timetable_service import who_is_busy_at
        from src.utils.db_handler import get_user_by_email

        faculty = get_user_by_email(scheduler_email)
        if not faculty:
            return {"success": False,
                    "message": "I couldn't resolve your faculty account."}
        if faculty.get("role") not in ("FACULTY", "ADMIN", "SUPER_ADMIN"):
            return {"success": False,
                    "message": "Only faculty/admin can start poll attendance."}

        subject = entities.get("target_subject") or entities.get("title")
        batch   = entities.get("target_batch")

        if not subject or not batch:
            now_class = who_is_busy_at(faculty["id"])
            if now_class:
                subject = subject or now_class.get("subject")
                batch   = batch   or now_class.get("batch")

        if not subject or not batch:
            return {"success": False, "needs_clarification": True,
                    "message": "Which subject and batch is this attendance "
                               "for? (e.g. 'start poll attendance for DSA "
                               "in CSE-3A')"}

        return start_session(faculty=faculty, batch=batch, subject=subject)

    # ------------------------------------------------------------------
    elif intent == "close_poll":
        # Faculty wants to close the most recent open poll session.
        if not scheduler_email:
            return {"success": False,
                    "error": "close_poll requires the faculty session."}

        from src.services.attendance_poll import (
            close_session,
            latest_open_for_faculty,
        )
        from src.utils.db_handler import get_user_by_email

        faculty = get_user_by_email(scheduler_email)
        if not faculty:
            return {"success": False,
                    "message": "I couldn't resolve your faculty account."}

        open_session = latest_open_for_faculty(faculty["id"])
        if not open_session:
            return {"success": False,
                    "message": "I couldn't find an open poll of yours to close."}

        result = close_session(open_session["id"])
        if result.get("success"):
            result.setdefault("message",
                              f"📊 Closed Quick Poll for "
                              f"{open_session['subject']}.")
        return result

    # ------------------------------------------------------------------
    elif intent == "override_attendance":
        # "mark Arjun present" / "mark Riya absent" — applies to the
        # faculty's most recent MCQ or Poll session.
        from datetime import date as _date

        from src.services.attendance_common import (
            latest_open_session_for_faculty,
            override_attendance,
        )
        from src.utils.db_handler import get_user_by_email

        faculty = get_user_by_email(scheduler_email) if scheduler_email else None
        if not faculty:
            return {"success": False,
                    "message": "I couldn't resolve your faculty account."}

        student = entities.get("target_faculty_name") or entities.get("title")
        if not student and entities.get("participants"):
            student = entities["participants"][0]
        status = (entities.get("target_status") or "").lower()
        if not student or status not in ("present", "absent"):
            return {"success": False, "needs_clarification": True,
                    "message": "Tell me who and which way — e.g. "
                               "<code>mark Arjun present</code>."}

        session = latest_open_session_for_faculty(faculty["id"])
        if not session:
            return {"success": False,
                    "message": "I couldn't find a recent attendance session "
                               "of yours to override."}

        return override_attendance(
            org_id=session["org_id"],
            faculty_id=session["faculty_id"],
            subject=session["subject"],
            batch=session["batch"],
            class_date=_date.today(),
            student_query=student,
            status=status,
            marked_by=faculty["id"],
            source=session.get("kind") or "manual",
            session_id=session["id"],
        )

    # ------------------------------------------------------------------
    elif intent == "query_my_next_class":
        # "what's my next class" — student-facing.
        if org_id is None or not scheduler_email:
            return {"success": False,
                    "error": "query_my_next_class requires the user session."}

        from src.services.timetable_service import next_class_for_batch
        from src.utils.db_handler import get_db_connection, release_db_connection

        # We need batch + full user row including batch and any extra.
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, role, batch FROM users WHERE email = %s LIMIT 1;",
                (scheduler_email,),
            )
            row = cur.fetchone()
            cur.close()
        finally:
            release_db_connection(conn)

        if not row:
            return {"success": False,
                    "message": "I couldn't find your account."}
        user_row = dict(row)
        batch = (user_row.get("batch") or "").strip()
        if not batch:
            return {"success": False, "needs_clarification": True,
                    "message": "I don't know which batch you're in yet. "
                               "Reply with your batch code (e.g. "
                               "<code>CSE-3A</code>) and I'll save it."}

        entry = next_class_for_batch(org_id, batch)
        if not entry:
            return {"success": True,
                    "message": (f"I couldn't find any classes for "
                                f"<b>{batch}</b> in the timetable. "
                                "Ask your faculty to upload one.")}

        subject  = entry.get("subject") or "your class"
        room     = entry.get("room")
        faculty  = entry.get("faculty_name") or "your professor"
        start_dt = entry["start_dt"]
        end_dt   = entry["end_dt"]

        if entry.get("in_session"):
            tail = f" until {end_dt.strftime('%H:%M')} — with {faculty}"
            where = f" in {room}" if room else ""
            msg = (f"You're in <b>{subject}</b>{where} right now"
                   f"{tail}.")
            return {"success": True, "data": entry, "message": msg}

        now = datetime.now()
        delta_min = int((start_dt - now).total_seconds() // 60)
        when_phrase = ""
        if start_dt.date() == now.date():
            if delta_min <= 0:
                when_phrase = f"at {start_dt.strftime('%H:%M')}"
            elif delta_min < 90:
                when_phrase = f"in {delta_min} minute{'s' if delta_min != 1 else ''}"
            else:
                when_phrase = f"at {start_dt.strftime('%H:%M')}"
        elif (start_dt.date() - now.date()).days == 1:
            when_phrase = f"tomorrow at {start_dt.strftime('%H:%M')}"
        else:
            when_phrase = (f"on {start_dt.strftime('%A')} at "
                           f"{start_dt.strftime('%H:%M')}")

        where = f" in {room}" if room else ""
        msg = (f"Your next class is <b>{subject}</b>{where} {when_phrase} "
               f"— with {faculty}.")
        return {"success": True, "data": entry, "message": msg}

    # ------------------------------------------------------------------
    elif intent == "query_attendance_sheet":
        # Faculty/admin: "bring up the attendance sheet for CS201"
        if org_id is None or not scheduler_email:
            return {"success": False,
                    "error": "query_attendance_sheet requires the faculty session."}

        from datetime import date as _date

        from src.services.attendance_query import fetch_sheet
        from src.utils.db_handler import get_user_by_email

        user = get_user_by_email(scheduler_email)
        if not user or user.get("role") not in (
            "FACULTY", "ADMIN", "SUPER_ADMIN",
        ):
            return {"success": False,
                    "message": "Only faculty/admin can pull a class "
                               "attendance sheet."}

        subject = entities.get("target_subject") or entities.get("title")
        if not subject:
            return {"success": False, "needs_clarification": True,
                    "message": ("Which subject? e.g. "
                                "<i>show CS201 attendance for today</i>")}

        # Date resolution: explicit query_date wins, else range, else today.
        def _parse_date(v):
            if not v:
                return None
            try:
                return _date.fromisoformat(str(v)[:10])
            except ValueError:
                return None

        class_date = _parse_date(entities.get("query_date"))
        date_from = _parse_date(entities.get("query_date_from"))
        date_to = _parse_date(entities.get("query_date_to"))
        if class_date is None and date_from is None and date_to is None:
            class_date = _date.today()

        return fetch_sheet(
            org_id=org_id,
            subject=subject,
            batch=entities.get("target_batch"),
            class_date=class_date,
            date_from=date_from,
            date_to=date_to,
        )

    # ------------------------------------------------------------------
    elif intent == "query_my_attendance":
        # Student: "what's my attendance?"
        if not scheduler_email:
            return {"success": False,
                    "error": "query_my_attendance requires the user session."}

        from src.services.attendance_query import fetch_my_summary
        from src.utils.db_handler import get_user_by_email

        user = get_user_by_email(scheduler_email)
        if not user:
            return {"success": False,
                    "message": "I couldn't find your account."}
        return fetch_my_summary(user["id"])

    # ------------------------------------------------------------------
    elif intent == "query_class_submissions":
        # Faculty: "who hasn't submitted assignment 3?"
        if org_id is None or not scheduler_email:
            return {"success": False,
                    "error": "query_class_submissions requires the faculty session."}

        from src.services.assignment_service import (
            list_open_for_faculty,
            submissions_for_assignment,
        )
        from src.utils.db_handler import get_user_by_email
        from src.utils.formatters import format_submissions

        faculty = get_user_by_email(scheduler_email)
        if not faculty or faculty.get("role") not in (
            "FACULTY", "ADMIN", "SUPER_ADMIN",
        ):
            return {"success": False,
                    "message": "Only faculty/admin can view class submissions."}

        candidates = list_open_for_faculty(org_id, faculty["id"])
        if not candidates:
            return {"success": True,
                    "message": "You haven't published any assignments yet."}

        subject = (entities.get("target_subject") or "").strip().lower()
        label = (entities.get("target_assignment_label") or "").strip().lower()

        # Filter by subject if given.
        pool = [a for a in candidates
                if not subject or subject in (a["subject"] or "").lower()]
        if not pool:
            pool = candidates

        # Pick by label (e.g. "assgn3" → match in title) if given.
        match = None
        if label:
            for a in pool:
                title = (a.get("title") or "").lower()
                if label in title or label.replace(" ", "") in title.replace(" ", ""):
                    match = a
                    break
        if match is None:
            # Fall back to most recent open assignment in the filtered pool.
            open_pool = [a for a in pool if a["status"] == "OPEN"]
            match = (open_pool or pool)[0]

        result = submissions_for_assignment(match["id"])
        if not result.get("success"):
            return result

        a = result["data"]["assignment"]
        msg = format_submissions(
            assignment_title=a["title"],
            subject=a["subject"],
            batch=a["batch"],
            due_at=a.get("due_at"),
            submitted=result["data"]["submitted"],
            missing=result["data"]["missing"],
        )
        result["message"] = msg
        return result

    # ------------------------------------------------------------------
    elif intent == "list_open_assignments_for_faculty":
        if org_id is None or not scheduler_email:
            return {"success": False,
                    "error": "list_open_assignments_for_faculty "
                             "requires the faculty session."}

        from src.services.assignment_service import list_open_for_faculty
        from src.utils.db_handler import get_user_by_email
        from src.utils.formatters import format_open_assignments

        faculty = get_user_by_email(scheduler_email)
        if not faculty or faculty.get("role") not in (
            "FACULTY", "ADMIN", "SUPER_ADMIN",
        ):
            return {"success": False,
                    "message": "Only faculty/admin can list class assignments."}

        rows = list_open_for_faculty(org_id, faculty["id"])
        msg = format_open_assignments(
            faculty_name=faculty.get("full_name") or "Faculty",
            rows=rows,
        )
        return {"success": True,
                "data": {"assignments": rows, "count": len(rows)},
                "message": msg}

    # ------------------------------------------------------------------
    elif intent == "list_class_roster":
        if org_id is None or not scheduler_email:
            return {"success": False,
                    "error": "list_class_roster requires the faculty session."}

        from src.services.attendance_query import list_class_roster as _roster
        from src.utils.db_handler import get_user_by_email

        user = get_user_by_email(scheduler_email)
        if not user or user.get("role") not in (
            "FACULTY", "ADMIN", "SUPER_ADMIN",
        ):
            return {"success": False,
                    "message": "Only faculty/admin can pull a class roster."}

        batch = entities.get("target_batch") or entities.get("group_name")
        return _roster(org_id=org_id, batch=batch)

    # ------------------------------------------------------------------
    elif intent == "generate_mcq_attendance":
        # Faculty: "generate mcq attendance for DSA"
        if org_id is None or not scheduler_email:
            return {"success": False,
                    "error": "generate_mcq_attendance requires the faculty session."}

        from src.services import course_materials, mcq_generator
        from src.utils.db_handler import get_user_by_email

        faculty = get_user_by_email(scheduler_email)
        if not faculty or faculty.get("role") not in (
            "FACULTY", "ADMIN", "SUPER_ADMIN",
        ):
            return {"success": False,
                    "message": "Only faculty/admin can generate attendance MCQs."}

        subject = entities.get("target_subject") or entities.get("title")
        if not subject:
            return {"success": False, "needs_clarification": True,
                    "message": ("Which subject? e.g. "
                                "<i>generate mcq attendance for DSA</i>")}
        try:
            count = int(entities.get("mcq_count") or 5)
        except (TypeError, ValueError):
            count = 5
        count = max(1, min(count, 10))

        result = mcq_generator.generate_for_subject(
            org_id=org_id, subject=subject, count=count,
        )
        if not result.get("success"):
            return result

        questions = result["questions"]
        bank_ids = course_materials.bulk_insert_questions(
            org_id=org_id,
            subject=subject,
            source_material_id=result.get("material_id"),
            questions=questions,
        )

        # Build a chat-friendly preview. Approval still happens via the
        # button card from the orchestrator's gen_mcq_ flow; for the REST
        # path we return the candidates inline.
        lines = [f"📝 <b>Drafted {len(questions)} MCQ(s) for {subject}</b>"]
        if result.get("material_title"):
            lines.append(f"<i>From: {result['material_title']}</i>")
        lines.append("")
        for i, q in enumerate(questions, start=1):
            lines.append(f"<b>Q{i}.</b> {q['question']}")
            for j, choice in enumerate(q["choices"]):
                marker = "✓" if j == q["correct_index"] else " "
                lines.append(f"   {marker} {chr(65 + j)}. {choice}")
            lines.append("")
        lines.append(
            "<i>Tap the Approve button on the bot's preview, or run "
            f"</i><code>start mcq attendance {subject}</code><i> after "
            "approval to launch the quiz.</i>"
        )

        return {
            "success": True,
            "data": {"bank_ids": bank_ids, "questions": questions,
                     "subject": subject},
            "message": "\n".join(lines),
        }

    # ------------------------------------------------------------------
    elif intent == "clarification_needed":
        return {
            "success":             False,
            "needs_clarification": True,
            "message":             intent_result.get("message", "Please provide more details."),
        }

    # ------------------------------------------------------------------
    else:
        return {"success": False, "error": f"Unknown or unsupported intent: {intent}"}
