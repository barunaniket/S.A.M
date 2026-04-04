"""
intent_router.py
----------------
Feature 1: End-to-end NLP orchestrator.

Receives a parsed intent dict from LLMProcessor and executes the corresponding
service call, returning a unified response.  Used by POST /api/v1/process/execute.
"""

from src.services.meeting_creator import create_meeting
from src.services.meeting_modifier import reschedule_meeting, cancel_meeting
from src.services.meeting_fetcher import search_meetings
from src.services.direct_email_service import DirectEmailService


def route_intent(intent_result: dict, scheduler_email: str) -> dict:
    """
    Route a parsed intent to the appropriate service and return its result.

    Parameters
    ----------
    intent_result  : dict returned by LLMProcessor.process_user_intent()
    scheduler_email: authenticated user's email from JWT (used as organiser)

    Supported intents:
        create_meeting, reschedule_meeting, cancel_meeting,
        list_meetings, send_email, clarification_needed
    """

    intent   = intent_result.get("intent")
    entities = intent_result.get("entities", {})

    # ------------------------------------------------------------------
    if intent == "create_meeting":
        title = entities.get("title") or "Untitled Meeting"
        if not entities.get("start_time") or not entities.get("end_time"):
            return {
                "success":          False,
                "needs_clarification": True,
                "message":          "Please specify the meeting start and end time.",
            }
        return create_meeting(
            title=title,
            start_datetime=entities["start_time"],
            end_datetime=entities["end_time"],
            participant_names=entities.get("participants", []),
            scheduler_email=scheduler_email,
        )

    # ------------------------------------------------------------------
    elif intent == "reschedule_meeting":
        meeting_id = entities.get("target_meeting_id")
        if not meeting_id:
            return {
                "success":          False,
                "needs_clarification": True,
                "message":          "Please provide the meeting ID to reschedule.",
            }
        if not entities.get("start_time") or not entities.get("end_time"):
            return {
                "success":          False,
                "needs_clarification": True,
                "message":          "Please specify the new start and end time.",
            }
        return reschedule_meeting(
            meeting_id=meeting_id,
            new_start_datetime=entities["start_time"],
            new_end_datetime=entities["end_time"],
            scheduler_email=scheduler_email,
        )

    # ------------------------------------------------------------------
    elif intent == "cancel_meeting":
        meeting_id = entities.get("target_meeting_id")
        if not meeting_id:
            return {
                "success":          False,
                "needs_clarification": True,
                "message":          "Please provide the meeting ID to cancel.",
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
                "success":          False,
                "needs_clarification": True,
                "message":          "Who should I send the email to?",
            }
        svc = DirectEmailService()
        return svc.send_email(
            target_name=target_name,
            subject=entities.get("title") or "Message from S.A.M.",
            message_body=intent_result.get("message") or "",
        )

    # ------------------------------------------------------------------
    elif intent == "clarification_needed":
        return {
            "success":          False,
            "needs_clarification": True,
            "message":          intent_result.get("message", "Please provide more details."),
        }

    # ------------------------------------------------------------------
    else:
        return {"success": False, "error": f"Unknown or unsupported intent: {intent}"}
