import json
import logging
import re
from datetime import datetime

from openai import OpenAI

from src.utils.config_loader import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LLMProcessor:
    """
    Cognitive engine of S.A.M.
    Translates natural-language user inputs into structured JSON intents
    using NVIDIA's OpenAI-compatible inference endpoint.

    Model + base URL come from Config (NVIDIA_BASE_URL, NVIDIA_MODEL_ID),
    so the deployed model can be swapped via .env without a code change.
    """

    def __init__(self):
        if not Config.NVIDIA_API_KEY:
            raise ValueError("NVIDIA_API_KEY is not set in config.")

        self.client = OpenAI(
            base_url=Config.NVIDIA_BASE_URL,
            api_key=Config.NVIDIA_API_KEY,
        )
        self.model_id = Config.NVIDIA_MODEL_ID
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        return """
You are S.A.M. (Smart Administrative Messenger), an intelligent agent for managing meetings and stakeholder communication at a university.
A faculty-in-charge talks to you, usually over WhatsApp. Your goal is to understand their commands and convert them into structured JSON actions.

### CAPABILITIES:
1. Schedule meetings (create_meeting)
2. Reschedule existing meetings (reschedule_meeting)
3. Cancel meetings (cancel_meeting)
4. Query/List meetings (list_meetings)
5. Send a single email (send_email)
6. Broadcast a message to many stakeholders via email + WhatsApp (broadcast_notification)
   - Targets can be a saved group ("send to CSE-3A"), a role+department, or a parsed upload.
7. Create a new saved group of users (create_group)
8. List all saved groups (list_groups)
9. Confirm a previously parsed file/upload action (confirm_upload)
10. Discard a previously parsed file/upload action (discard_upload)

### RULES:
- Output ONLY valid JSON. No markdown, no code fences, no commentary.
- Date Handling: ALWAYS convert relative dates (e.g. "tomorrow at 3 PM") into ISO 8601
  (YYYY-MM-DDTHH:MM:SS) based on the "Current Reference Time" provided.
- Participant Handling: Extract names exactly as typed.
- Missing Info: If critical info is missing for a 'create' / 'broadcast' intent, set intent to "clarification_needed".
- If the session context contains a `pending_upload_id`, prefer the intents `confirm_upload` or `discard_upload`
  when the user replies affirmatively/negatively about the uploaded file.

### OUTPUT SCHEMA:
{
  "intent": "create_meeting" | "reschedule_meeting" | "cancel_meeting" | "list_meetings" | "send_email" | "broadcast_notification" | "create_group" | "list_groups" | "confirm_upload" | "discard_upload" | "clarification_needed",
  "entities": {
    "title": "string or null",
    "participants": ["name1", "name2"],
    "start_time": "ISO_8601 or null",
    "end_time": "ISO_8601 or null",
    "location": "string or null",
    "agenda": "string or null",
    "target_meeting_id": "string or null",
    "target_role": "ADMIN | FACULTY | STUDENT or null",
    "target_department": "string or null",
    "target_group_name": "string or null",
    "group_name": "string or null",
    "members_emails": ["email1", "email2"],
    "description": "string or null",
    "pending_upload_id": "integer or null",
    "channels": ["email", "whatsapp"],
    "body": "string or null"
  },
  "confidence": 0.0-1.0,
  "message": "optional user-facing message"
}

### UPLOAD CONFIRMATION RULES:
When the session context contains a `pending_upload_id` AND the user provides
meeting details (a date/time, optionally a location/title), set:
  - `intent` = "confirm_upload"
  - `title`  = meeting title (best guess, e.g. "Faculty meeting")
  - `start_time` = ISO 8601 of the meeting start
  - `end_time` = ISO 8601 of the meeting end (default: start + 1 hour if not given)
  - `location` and `agenda` if mentioned
This will create a meeting and notify all attendees in the upload with reminders.
If the user provides only a message body (no time), still set "confirm_upload"
but leave start_time null — the system will fall back to a one-shot broadcast.
"""

    def _clean_json_response(self, raw_text: str) -> str:
        cleaned = (raw_text or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(json)?", "", cleaned)
            cleaned = re.sub(r"```$", "", cleaned)
        return cleaned.strip()

    def process_user_intent(self, user_input: str, session_context: dict = None) -> dict:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        user_message = (
            f"### CURRENT CONTEXT:\n"
            f"- Current Reference Time: {current_time}\n"
            f'- User Input: "{user_input}"\n'
        )
        if session_context:
            user_message += f"- Session Context: {json.dumps(session_context, default=str)}\n"

        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,
                top_p=1,
                max_tokens=2048,
            )

            raw_text = response.choices[0].message.content if response.choices else ""
            cleaned_text = self._clean_json_response(raw_text)
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
