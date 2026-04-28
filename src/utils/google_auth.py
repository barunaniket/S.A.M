import os
import httpx
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from cryptography.fernet import Fernet

import jwt
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.utils.config_loader import Config


class GoogleAuthService:
    def __init__(self):
        self.client_id = Config.GOOGLE_CLIENT_ID
        self.client_secret = Config.GOOGLE_CLIENT_SECRET
        self.redirect_uri = Config.GOOGLE_REDIRECT_URI

        key = os.getenv("ENCRYPTION_KEY")
        if not key:
            print("WARNING: ENCRYPTION_KEY not found. Generating temporary key (lost on restart).")
            key = Fernet.generate_key().decode()
        self.cipher = Fernet(key.encode())

        self.AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
        self.TOKEN_URL = "https://oauth2.googleapis.com/token"
        self.USER_INFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

    def get_login_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile https://www.googleapis.com/auth/calendar.events",
            "access_type": "offline",
            "prompt": "consent",
            "state": state
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(self.TOKEN_URL, data=data)
            if resp.status_code != 200:
                return {"error": "Failed to exchange code", "details": resp.json()}
            return resp.json()

    async def get_user_info(self, access_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = await client.get(self.USER_INFO_URL, headers=headers)
            return resp.json()

    def encrypt_token(self, token: str) -> str:
        if not token:
            return None
        return self.cipher.encrypt(token.encode()).decode()

    def decrypt_token(self, encrypted_token: str) -> str:
        if not encrypted_token:
            return None
        return self.cipher.decrypt(encrypted_token.encode()).decode()


# ---------------------------------------------------------------------------
# Standalone helpers used by services
# ---------------------------------------------------------------------------

def _get_cipher() -> Fernet:
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("ENCRYPTION_KEY is not set in .env")
    return Fernet(key.encode())


def get_calendar_service(user_email: str = None, credentials_dict: dict = None):
    """
    Build and return an authenticated Google Calendar API service.

    Priority:
    1. credentials_dict — supply raw token data directly (useful for tests).
    2. user_email — load stored tokens from the DB for this user.

    Raises ValueError if neither is provided or if no stored credentials exist.
    """
    from src.utils.db_handler import get_user_by_email

    if credentials_dict:
        creds = Credentials(
            token=credentials_dict.get("access_token"),
            refresh_token=credentials_dict.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=Config.GOOGLE_CLIENT_ID,
            client_secret=Config.GOOGLE_CLIENT_SECRET,
        )
    elif user_email:
        user = get_user_by_email(user_email)
        if not user:
            raise ValueError(f"User '{user_email}' not found in database")

        access_token = user.get("access_token")
        encrypted_rt = user.get("encrypted_refresh_token")

        refresh_token = None
        if encrypted_rt:
            try:
                cipher = _get_cipher()
                refresh_token = cipher.decrypt(encrypted_rt.encode()).decode()
            except Exception:
                refresh_token = None

        if not access_token and not refresh_token:
            raise ValueError(f"No valid Google credentials stored for '{user_email}'")

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=Config.GOOGLE_CLIENT_ID,
            client_secret=Config.GOOGLE_CLIENT_SECRET,
        )
    else:
        raise ValueError("get_calendar_service() requires user_email or credentials_dict")

    return build("calendar", "v3", credentials=creds)


def create_jwt_token(user_id: int, org_id: int, email: str = None,
                     role: str = None) -> str:
    """
    Create a signed JWT with user_id, org_id, and role claims.
    The frontend stores this and sends it as Bearer token on every request.
    The middleware reads `role` to populate request.state.role for RBAC.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=Config.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "user_id": user_id,
        "org_id": org_id,
        "exp": expire,
    }
    if email:
        payload["email"] = email
    if role:
        payload["role"] = role

    return jwt.encode(payload, Config.SECRET_KEY, algorithm=Config.ALGORITHM)


async def refresh_access_token(refresh_token: str) -> dict:
    """
    Exchange a refresh token for a new access token from Google.
    Returns the raw token response dict (includes access_token, expires_in, etc.).
    """
    data = {
        "client_id": Config.GOOGLE_CLIENT_ID,
        "client_secret": Config.GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data=data)
        return resp.json()
