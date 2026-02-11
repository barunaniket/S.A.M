from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from src.utils.google_auth import GoogleAuthService

# Initialize Router
router = APIRouter(prefix="/auth", tags=["Authentication"])
auth_service = GoogleAuthService()

# Request Model
class LoginRequest(BaseModel):
    code: str
    state: str = None  # Optional

@router.get("/login-url")
async def get_url():
    """
    Returns the Google Login URL.
    """
    # In a real app, generate a random state here and save it to Redis
    state = "secure_random_state"
    url = auth_service.get_login_url(state)
    return {"url": url}

@router.post("/callback")
async def auth_callback(payload: LoginRequest):
    """
    Handles the redirect from Google. Swaps code for tokens.
    """
    # 1. Exchange Code for Tokens
    tokens = await auth_service.exchange_code(payload.code)
    
    if "error" in tokens:
        raise HTTPException(status_code=400, detail=tokens)

    # 2. Get User Profile (Email, Name, Avatar)
    user_info = await auth_service.get_user_info(tokens["access_token"])
    
    # 3. Encrypt the Refresh Token
    refresh_token = tokens.get("refresh_token")
    encrypted_rt = None
    if refresh_token:
        encrypted_rt = auth_service.encrypt_token(refresh_token)
        # TODO: Save 'encrypted_rt' and 'user_info' into your Postgres 'users' table here.
    
    return {
        "message": "Login Successful",
        "user": {
            "name": user_info.get("name"),
            "email": user_info.get("email"),
            "picture": user_info.get("picture")
        },
        "access_token": tokens["access_token"], # Temporary: In prod, issue your own JWT here.
        "has_refresh_token": encrypted_rt is not None
    }