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
    "NVIDIA_API_KEY",
    "DATABASE_URL",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_VERIFY_TOKEN",
    "WHATSAPP_APP_SECRET",
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

    # AI Model — NVIDIA OpenAI-compatible endpoint (default model is a Gemma
    # variant served by NVIDIA; can be swapped via NVIDIA_MODEL_ID in .env).
    NVIDIA_API_KEY  = os.getenv("NVIDIA_API_KEY")
    NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    NVIDIA_MODEL_ID = os.getenv("NVIDIA_MODEL_ID", "google/gemma-3-27b-it")
    GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY")  # kept for optional Google-direct usage

    # WhatsApp (Meta Cloud API)
    WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
    WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
    WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")
    WHATSAPP_GRAPH_VERSION = os.getenv("WHATSAPP_GRAPH_VERSION", "v20.0")

    # Telegram Bot API. Optional — if TELEGRAM_BOT_TOKEN is unset the poller
    # refuses to start and the /me/telegram/* routes return "not configured".
    # This keeps existing dev setups working without a Telegram bot.
    TELEGRAM_BOT_TOKEN     = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_BOT_USERNAME  = os.getenv("TELEGRAM_BOT_USERNAME")  # @-less, used to build deep links
    TELEGRAM_API_BASE      = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org")
    TELEGRAM_POLL_TIMEOUT  = int(os.getenv("TELEGRAM_POLL_TIMEOUT", "25"))

    # Uploads
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "data/uploads")

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
    Thin wrapper around the NVIDIA OpenAI-compatible inference endpoint so
    service modules can call client.generate(system_prompt=..., user_prompt=...)
    without knowing the underlying SDK details.
    """

    def __init__(self):
        from openai import OpenAI
        self._client = OpenAI(
            base_url=Config.NVIDIA_BASE_URL,
            api_key=Config.NVIDIA_API_KEY,
        )
        self._model_id = Config.NVIDIA_MODEL_ID

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """
        Returns the text response from the LLM given a system + user prompt.
        Raises on API errors — callers should handle exceptions.
        """
        response = self._client.chat.completions.create(
            model=self._model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            top_p=1,
            max_tokens=2048,
        )
        return response.choices[0].message.content if response.choices else ""


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