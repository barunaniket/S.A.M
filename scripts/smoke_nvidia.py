"""
Live-fire smoke test against NVIDIA's hosted z-ai/glm-5.1 endpoint.

Three checks:

  1. Raw OpenAI-client round-trip — confirms the key + base URL work.
  2. LLMProcessor.process_user_intent — confirms our intent JSON contract
     parses (faculty teacher chatting over WhatsApp).
  3. file_ingestor.extract_meeting_metadata — confirms the meeting-from-file
     extraction prompt returns valid JSON for a realistic input.

Run from repo root:

    PYTHONPATH=. .venv/bin/python scripts/smoke_nvidia.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Stand-in values for keys the smoke test doesn't actually need so
# Config.validate() doesn't fail-fast before we even reach NVIDIA.
for _k, _v in {
    "WHATSAPP_PHONE_NUMBER_ID": "smoke",
    "WHATSAPP_ACCESS_TOKEN":    "smoke",
    "WHATSAPP_VERIFY_TOKEN":    "smoke",
    "WHATSAPP_APP_SECRET":      "smoke",
}.items():
    os.environ.setdefault(_k, _v)

from src.utils.config_loader import Config


def banner(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


# ---------------------------------------------------------------------------
# 1. Raw client round-trip
# ---------------------------------------------------------------------------
def check_raw():
    banner("1. Raw OpenAI client → NVIDIA round-trip")
    from openai import OpenAI

    client = OpenAI(base_url=Config.NVIDIA_BASE_URL, api_key=Config.NVIDIA_API_KEY)
    resp = client.chat.completions.create(
        model=Config.NVIDIA_MODEL_ID,
        messages=[
            {"role": "system", "content": "Reply with the single word: pong"},
            {"role": "user",   "content": "ping"},
        ],
        temperature=0.0,
        max_tokens=16,
    )
    text = resp.choices[0].message.content if resp.choices else ""
    print(f"model: {Config.NVIDIA_MODEL_ID}")
    print(f"reply: {text!r}")
    assert text and "pong" in text.lower(), "did not see 'pong' in response"
    print("✅ raw round-trip OK")


# ---------------------------------------------------------------------------
# 2. Intent parser
# ---------------------------------------------------------------------------
def check_intent_parser():
    banner("2. LLMProcessor.process_user_intent")
    from src.services.llm_processor import LLMProcessor

    p = LLMProcessor()

    cases = [
        "Schedule a meeting with Aniket and Mayank tomorrow at 4pm for 1 hour",
        "Cancel meeting MID-12345",
        "Send everyone in CSE-3A a reminder about the lab tomorrow at 9am",
        "Create a group called CSE-3A with members a@uni.edu, b@uni.edu",
        "yes",  # confirmation-style
    ]
    for q in cases:
        r = p.process_user_intent(q, session_context={"channel": "whatsapp"})
        print(f"\n  > {q}")
        print(f"    intent: {r.get('intent')}")
        print(f"    entities: {json.dumps(r.get('entities'), default=str)[:200]}")
        assert r.get("intent") and r.get("intent") != "error", f"bad intent for: {q}"
    print("\n✅ intent parser returning valid JSON for every prompt")


# ---------------------------------------------------------------------------
# 3. Meeting extraction
# ---------------------------------------------------------------------------
def check_meeting_extraction():
    banner("3. file_ingestor.extract_meeting_metadata")
    from src.services.file_ingestor import extract_meeting_metadata

    with_meeting = {
        "kind": "text",
        "text": (
            "FACULTY MEETING\n"
            "All CSE faculty are requested to attend a meeting on "
            "4 May 2026 from 4:00 PM to 5:00 PM in Conference Room 302.\n"
            "Agenda: mid-term assessment planning."
        ),
    }
    no_meeting = {
        "kind": "text",
        "text": "Aniket Barun, Mayank Rao, Krishna K. — student attendee list.",
    }

    a = extract_meeting_metadata(with_meeting)
    b = extract_meeting_metadata(no_meeting)
    print(f"  with-meeting → found={a.get('found')}, "
          f"start={a.get('start_time')}, location={a.get('location')!r}")
    print(f"  no-meeting   → found={b.get('found')}")

    assert a.get("found") is True,        "expected found=True for with-meeting input"
    assert a.get("start_time"),           "expected a start_time"
    assert b.get("found") is False,       "expected found=False for attendee-only input"
    print("✅ meeting extraction discriminates correctly")


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not Config.NVIDIA_API_KEY:
        print("NVIDIA_API_KEY is not set — abort.")
        sys.exit(1)

    check_raw()
    check_intent_parser()
    check_meeting_extraction()

    banner("ALL SMOKE CHECKS PASSED")
