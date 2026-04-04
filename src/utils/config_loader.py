'''
agar kissi koo janna hai ki kya karta hai yea file.
toh yea basically ek loader and validator dono sath me hai.
bar bar iss code ko manually har ek service me load krne kee jagah 
directly iss module koo import kr lenge
'''

import os
import re
import sys
from dotenv import load_dotenv

load_dotenv()

REQUIRED_KEYS = [
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_PROJECT_ID",
    "GOOGLE_API_SCOPES",
    "SENDER_EMAIL",
    "SENDER_PASSWORD",
    "GEMINI_API_KEY",
    "DATABASE_URL"
]

class Config:
    """
    Central configuration class.
    Access variables like: Config.GOOGLE_CLIENT_ID
    """

    # Google API Credentials
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

    _scopes_str = os.getenv("GOOGLE_API_SCOPES", "")
    GOOGLE_API_SCOPES = _scopes_str.split(" ") if _scopes_str else []

    # Email Credentials
    SENDER_EMAIL = os.getenv("SENDER_EMAIL")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

    # AI Model
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    # Database
    DATABASE_URL = os.getenv("DATABASE_URL")

    # Auth
    SECRET_KEY = os.getenv("SECRET_KEY")
    ALGORITHM = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

    # Redis
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

    @classmethod
    def validate(cls):
        missing_keys = [k for k in REQUIRED_KEYS if not os.getenv(k)]
        if missing_keys:
            print(f"CRITICAL ERROR: Missing configuration keys in .env: {', '.join(missing_keys)}")
            print("Please update your .env file with the correct credentials.")
            sys.exit(1)


Config.validate()


# ---------------------------------------------------------------------------
# Standalone helpers (imported directly by service modules)
# ---------------------------------------------------------------------------

def get_env(key: str, default: str = None) -> str:
    """Simple os.getenv wrapper so modules can call get_env('KEY')."""
    return os.getenv(key, default)


def sanitize_text(text: str) -> str:
    """Strip whitespace and remove HTML/script tags from user-supplied text."""
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"<[^>]+>", "", text)       # strip HTML tags
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)  # strip control chars
    return text


class _LLMClient:
    """
    Thin wrapper around the Google GenAI client so service modules can call
    client.generate(system_prompt=..., user_prompt=...) without knowing the
    underlying SDK details.
    """

    def __init__(self):
        from google import genai
        from google.genai import types as genai_types
        self._genai_types = genai_types
        self._client = genai.Client(api_key=Config.GEMINI_API_KEY)
        self._model_id = "gemini-2.0-flash-lite-preview-02-05"

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """
        Returns the text response from Gemini given a system + user prompt.
        Raises on API errors — callers should handle exceptions.
        """
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        response = self._client.models.generate_content(
            model=self._model_id,
            contents=full_prompt,
            config=self._genai_types.GenerateContentConfig(temperature=0.0),
        )
        return response.text


def get_llm_client() -> _LLMClient:
    """Return an initialised LLM client. Called at module/class init time."""
    return _LLMClient()


'''
kaise iss config koo use krna hai is below

from utils.config_loader import Config #pehele import kiya module koo

def send_meeting_email(to_email, details):
    sender = Config.SENDER_EMAIL #and simply config kee thru use kr liya
    password = Config.SENDER_PASSWORD
    # ... rest of code
'''