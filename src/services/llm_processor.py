import json
import logging
import re
from datetime import datetime

from google import genai
from google.genai import types

from src.utils.config_loader import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LLMProcessor:
    """
    Cognitive engine of S.A.M.
    Translates natural-language user inputs into structured JSON intents.
    """

    def __init__(self):
        if not Config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set in config.")

        self.client = genai.Client(api_key=Config.GEMINI_API_KEY)
        self.model_id = "gemini-2.0-flash-lite-preview-02-05"
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        return """
You are S.A.M. (Smart Administrative Messenger), an intelligent agent for managing meetings at a university.
Your goal is to understand user commands and convert them into structured JSON actions.

### CAPABILITIES:
1. Schedule meetings (create_meeting)
2. Reschedule existing meetings (reschedule_meeting)
3. Cancel meetings (cancel_meeting)
4. Query/List meetings (list_meetings)
5. Send generic emails (send_email)

### RULES:
- Output ONLY valid JSON. No markdown, no code fences.
- Date Handling: ALWAYS convert relative dates (e.g. "tomorrow at 3 PM") into ISO 8601
  (YYYY-MM-DDTHH:MM:SS) based on the "Current Reference Time" provided.
- Participant Handling: Extract names exactly as typed.
- Missing Info: If critical info is missing for a 'create' intent, set intent to "clarification_needed".

### OUTPUT SCHEMA:
{
  "intent": "create_meeting" | "reschedule_meeting" | "cancel_meeting" | "list_meetings" | "send_email" | "clarification_needed",
  "entities": {
    "title": "string or null",
    "participants": ["name1", "name2"],
    "start_time": "ISO_8601 or null",
    "end_time": "ISO_8601 or null",
    "target_meeting_id": "string or null"
  },
  "confidence": 0.0-1.0,
  "message": "optional user-facing message"
}
"""

    def _clean_json_response(self, raw_text: str) -> str:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(json)?", "", cleaned)
            cleaned = re.sub(r"```$", "", cleaned)
        return cleaned.strip()

    def process_user_intent(self, user_input: str, session_context: dict = None) -> dict:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        dynamic_prompt = f"""{self.system_prompt}

### CURRENT CONTEXT:
- Current Reference Time: {current_time}
- User Input: "{user_input}"
"""
        if session_context:
            dynamic_prompt += f"- Context: {session_context}\n"

        try:
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=dynamic_prompt,
                config=types.GenerateContentConfig(temperature=0.0),
            )

            cleaned_text = self._clean_json_response(response.text)
            parsed_data = json.loads(cleaned_text)

            logger.info("Intent: %s (conf: %s)", parsed_data.get("intent"), parsed_data.get("confidence"))
            return parsed_data

        except Exception as e:
            logger.error("LLM error: %s", e)
            return {
                "intent": "error",
                "message": "I had trouble understanding that request. Please try again.",
                "reasoning": str(e),
            }
