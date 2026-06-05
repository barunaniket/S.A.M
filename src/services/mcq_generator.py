"""
mcq_generator.py
----------------
Generate N MCQ candidates from a course-material PDF (or any text source)
using the same NVIDIA OpenAI-compatible endpoint that LLMProcessor uses.

The generator is a pure function over text — it does not write to the DB
itself. Callers pass the result to course_materials.bulk_insert_questions
once they want to persist.

Public API:

    generate_from_text(subject, text, *, count=5) -> dict
        Returns {success, questions, message, error_code?}.
        On success: questions = [{"question", "choices", "correct_index"}].

    generate_for_subject(org_id, subject, *, count=5) -> dict
        Convenience wrapper: looks up the most recent approved-text
        material via course_materials.latest_with_text() and runs
        generate_from_text() on it. Returns the same shape plus
        `material_id` and `material_title`.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from openai import OpenAI

from src.services import course_materials
from src.utils.config_loader import Config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def _build_prompt(subject: str, count: int) -> str:
    return (
        "You are an exam-question writer for a university course. "
        "Read the source material below and write rapid-fire MCQs that a "
        "student can answer in 5–10 seconds each.\n\n"
        f"Subject: {subject}\n"
        f"Number of questions: {count}\n\n"
        "Hard rules:\n"
        "- Output ONLY a JSON array. No markdown, no commentary, no fences.\n"
        "- Each item: {\"question\": str, \"choices\": [str, str, str, str], "
        "\"correct_index\": int (0-3)}\n"
        "- Choices must be plausible. correct_index must be the actual answer.\n"
        "- Questions must be answerable from the source material alone.\n"
        "- Keep each question + choices short (≤ 18 words per choice).\n"
    )


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _client() -> OpenAI:
    return OpenAI(
        base_url=Config.NVIDIA_BASE_URL,
        api_key=Config.NVIDIA_API_KEY,
    )


def _trim_text(text: str, max_chars: int = 8000) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    # Keep the start (lecture intro) + a tail (often summary slides).
    head = text[: int(max_chars * 0.7)]
    tail = text[-int(max_chars * 0.3):]
    return f"{head}\n\n... [truncated] ...\n\n{tail}"


def _clean_json(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(json)?", "", s)
        s = re.sub(r"```$", "", s)
    return s.strip()


def _validate_questions(arr: Any) -> List[Dict[str, Any]]:
    """Drop malformed entries, keep the well-shaped ones."""
    out: List[Dict[str, Any]] = []
    if not isinstance(arr, list):
        return out
    for item in arr:
        if not isinstance(item, dict):
            continue
        q = item.get("question")
        choices = item.get("choices")
        idx = item.get("correct_index")
        if not isinstance(q, str) or not q.strip():
            continue
        if not isinstance(choices, list) or len(choices) != 4:
            continue
        if not all(isinstance(c, str) and c.strip() for c in choices):
            continue
        try:
            idx_int = int(idx)
        except (TypeError, ValueError):
            continue
        if idx_int < 0 or idx_int > 3:
            continue
        out.append({
            "question": q.strip(),
            "choices": [c.strip() for c in choices],
            "correct_index": idx_int,
        })
    return out


def generate_from_text(subject: str, text: str, *,
                       count: int = 5) -> Dict[str, Any]:
    if not subject or not subject.strip():
        return {"success": False, "error_code": "MISSING_SUBJECT",
                "message": "Subject is required."}
    if not text or len(text.strip()) < 100:
        return {"success": False, "error_code": "INSUFFICIENT_TEXT",
                "message": "Source material is too short — give me at "
                           "least a paragraph of class notes/slides."}

    count = max(1, min(int(count), 10))
    prompt = _build_prompt(subject, count)
    user_msg = f"{prompt}\n\n--- SOURCE MATERIAL ---\n{_trim_text(text)}"

    try:
        client = _client()
        resp = client.chat.completions.create(
            model=Config.NVIDIA_MODEL_ID,
            messages=[
                {"role": "system",
                 "content": "Return ONLY valid JSON arrays. No prose."},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,
            top_p=1,
            max_tokens=2048,
        )
        raw = resp.choices[0].message.content if resp.choices else ""
    except Exception as e:
        logger.exception("MCQ generator LLM call failed")
        return {"success": False, "error_code": "LLM_ERROR",
                "message": f"LLM call failed: {e}"}

    cleaned = _clean_json(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("MCQ generator: malformed JSON: %s\n--\n%s",
                       e, cleaned[:400])
        return {"success": False, "error_code": "BAD_JSON",
                "message": "I couldn't parse the LLM's output — try again."}

    questions = _validate_questions(parsed)
    if not questions:
        return {"success": False, "error_code": "NO_VALID_QUESTIONS",
                "message": "The LLM didn't return any well-formed questions."}

    return {"success": True, "questions": questions[:count],
            "message": f"Drafted {len(questions[:count])} question(s)."}


def generate_for_subject(org_id: int, subject: str, *,
                         count: int = 5) -> Dict[str, Any]:
    """
    Look up the most recent approved-text material for this subject,
    pump its text through the LLM, and return the candidates. Caller
    persists them via course_materials.bulk_insert_questions.
    """
    material = course_materials.latest_with_text(org_id, subject)
    if not material:
        return {"success": False, "error_code": "NO_MATERIAL",
                "message": (f"No course material on file for <b>{subject}</b>. "
                            "Send me a PDF with caption "
                            f"<code>material {subject}</code> first.")}

    res = generate_from_text(subject, material.get("extracted_text") or "",
                              count=count)
    if res.get("success"):
        res["material_id"] = material["id"]
        res["material_title"] = material.get("title")
    return res
