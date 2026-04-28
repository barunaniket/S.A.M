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
        if not entities.get("start_time") or not entities.get("end_time"):
            return {
                "success":             False,
                "needs_clarification": True,
                "message":             "Please specify the meeting start and end time.",
            }
        return create_meeting(
            title=title,
            start_datetime=entities["start_time"],
            end_datetime=entities["end_time"],
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
                    "assign_tasks", "confirm_tasks", "discard_tasks"):
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
        # Resolves faculty name fuzzily, looks up timetable + active meeting
        # at the requested time. Available to STUDENT, FACULTY, ADMIN.
        if org_id is None:
            return {"success": False, "error": "query_faculty_status requires org_id context."}

        from src.services.timetable_service import (
            format_busy_status,
            resolve_faculty_by_name,
            who_is_busy_at,
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

        # Parse the requested time. LLM should hand us ISO; if not, default
        # to "right now".
        when_dt = None
        when_label = "right now"
        qt = entities.get("query_time")
        if qt:
            try:
                when_dt = datetime.fromisoformat(qt.replace("Z", ""))
                when_label = f"at {when_dt.strftime('%H:%M on %A')}"
            except ValueError:
                when_dt = None

        entry = who_is_busy_at(faculty["id"], when_dt)
        msg = format_busy_status(faculty["full_name"], entry, at_label=when_label)

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
    elif intent == "clarification_needed":
        return {
            "success":             False,
            "needs_clarification": True,
            "message":             intent_result.get("message", "Please provide more details."),
        }

    # ------------------------------------------------------------------
    else:
        return {"success": False, "error": f"Unknown or unsupported intent: {intent}"}
