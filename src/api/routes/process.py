import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from src.services.llm_processor import LLMProcessor
from src.services.clarification_agent import get_clarification
from src.services.intent_router import route_intent

router = APIRouter()

_processor = None


def _get_processor() -> LLMProcessor:
    global _processor
    if _processor is None:
        _processor = LLMProcessor()
    return _processor


class ProcessRequest(BaseModel):
    user_input: str
    session_context: Optional[dict] = None


class ClarificationRequest(BaseModel):
    missing_fields: list
    context: Optional[dict] = None


@router.post("/process")
async def api_process_intent(body: ProcessRequest, request: Request):
    """
    Core S.A.M. NLP endpoint.

    Send a natural-language command and receive a structured JSON intent.
    The frontend is responsible for calling the relevant action endpoint.

    Possible intent values:
        create_meeting, reschedule_meeting, cancel_meeting,
        list_meetings, send_email, clarification_needed, error
    """
    processor = _get_processor()
    # The LLM call is synchronous/blocking — run it off the event loop so one
    # in-flight request doesn't stall every other connection on this worker.
    result = await asyncio.to_thread(
        processor.process_user_intent,
        user_input=body.user_input,
        session_context=body.session_context,
    )

    if result.get("intent") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))

    return result


@router.post("/process/execute")
async def api_execute_intent(body: ProcessRequest, request: Request):
    """
    Feature 1 — End-to-end NLP orchestrator.

    Send a natural-language command and S.A.M. will:
      1. Parse the intent (NVIDIA / OpenAI-compatible LLM)
      2. Execute the corresponding action (create / reschedule / cancel / list / email / broadcast)
      3. Trigger notifications automatically
      4. Return the combined result

    Requires a valid JWT with the user's email.
    """
    scheduler_email = getattr(request.state, "email", None)
    org_id          = getattr(request.state, "org_id", None)
    if not scheduler_email:
        raise HTTPException(
            status_code=400,
            detail="scheduler email not available — ensure email is included in JWT",
        )

    processor = _get_processor()
    # Both the LLM parse and the downstream action dispatch are blocking
    # (LLM HTTP + DB/Google calls) — keep them off the async event loop.
    intent_result = await asyncio.to_thread(
        processor.process_user_intent,
        user_input=body.user_input,
        session_context=body.session_context,
    )

    if intent_result.get("intent") == "error":
        raise HTTPException(status_code=500, detail=intent_result.get("message"))

    result = await asyncio.to_thread(
        route_intent, intent_result, scheduler_email, org_id=org_id
    )

    return {
        "intent":  intent_result,
        "result":  result,
    }


@router.post("/process/clarify")
async def api_get_clarification(body: ClarificationRequest):
    """
    Generate targeted clarification questions for missing meeting details.
    Used when the LLM returns intent = "clarification_needed".
    """
    question = await asyncio.to_thread(
        get_clarification,
        missing_fields=body.missing_fields,
        context=body.context or {},
    )
    return {"question": question}
