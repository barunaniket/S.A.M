import os
import httpx
from urllib.parse import urlencode
from cryptography.fernet import Fernet

class GoogleAuthService:
    def __init__(self):
        # 1. Load Secrets from .env
        self.client_id = os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        self.redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
        
        # 2. Setup Encryption (For Refresh Tokens)
        # We try to get the key from .env. If missing, we generate a temporary one 
        # (WARNING: Temporary keys are lost on restart, so you MUST set ENCRYPTION_KEY in .env)
        key = os.getenv("ENCRYPTION_KEY")
        if not key:
            print("WARNING: ENCRYPTION_KEY not found in .env. Generating temporary key.")
            key = Fernet.generate_key().decode()
        self.cipher = Fernet(key.encode())

        # 3. Google API Endpoints
        self.AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
        self.TOKEN_URL = "https://oauth2.googleapis.com/token"
        self.USER_INFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

    def get_login_url(self, state: str) -> str:
        """
        Generates the 'Sign in with Google' link.
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile https://www.googleapis.com/auth/calendar.events",
            "access_type": "offline",  # CRITICAL: Forces Google to give us a Refresh Token
            "prompt": "consent",       # Forces the 'Allow' screen every time
            "state": state
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        """
        Swaps the temporary 'Auth Code' for real Access & Refresh Tokens.
        """
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
        """
        Uses the Access Token to get the user's Email, Name, and Picture.
        """
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = await client.get(self.USER_INFO_URL, headers=headers)
            return resp.json()

    def encrypt_token(self, token: str) -> str:
        """
        Encrypts sensitive data (like Refresh Tokens) before DB storage.
        """
        if not token:
            return None
        return self.cipher.encrypt(token.encode()).decode()

    def decrypt_token(self, encrypted_token: str) -> str:
        """
        Decrypts data when we need to use it.
        """
        if not encrypted_token:
            return None
        return self.cipher.decrypt(encrypted_token.encode()).decode()