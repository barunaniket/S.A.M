from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.utils.google_auth import GoogleAuthService, create_jwt_token
from src.utils.db_handler import upsert_google_user

router = APIRouter(prefix="/auth", tags=["Authentication"])
auth_service = GoogleAuthService()


class LoginRequest(BaseModel):
    code: str
    state: str = None


@router.get("/login-url")
async def get_login_url():
    """
    Returns the Google OAuth login URL.
    The frontend redirects the user to this URL to begin the login flow.
    """
    state = "secure_random_state"
    url = auth_service.get_login_url(state)
    return {"url": url}


@router.post("/callback")
async def auth_callback(payload: LoginRequest):
    """
    Handles the OAuth callback from the frontend.

    Flow:
    1. Exchange the temporary code for Google tokens.
    2. Fetch the user's Google profile.
    3. Persist / update user in DB (upsert).
    4. Issue our own JWT (contains user_id + org_id).
    5. Return the JWT to the frontend.
    """
    # 1. Exchange code for tokens
    tokens = await auth_service.exchange_code(payload.code)

    if "error" in tokens:
        raise HTTPException(status_code=400, detail=tokens)

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")

    # 2. Fetch user profile from Google
    user_info = await auth_service.get_user_info(access_token)

    email = user_info.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Could not retrieve email from Google")

    # 3. Encrypt the refresh token before storing
    encrypted_rt = auth_service.encrypt_token(refresh_token) if refresh_token else None

    # 4. Upsert user in DB
    try:
        user = upsert_google_user(
            email=email,
            full_name=user_info.get("name", email),
            picture=user_info.get("picture"),
            access_token=access_token,
            encrypted_refresh_token=encrypted_rt,
            org_id=1,  # Default org; extend to invite-code flow as needed
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to persist user: {str(e)}")

    # 5. Issue our own JWT
    jwt_token = create_jwt_token(
        user_id=user["id"],
        org_id=user["org_id"],
        email=email,
        role=user.get("role"),
    )

    return {
        "message": "Login successful",
        "token": jwt_token,
        "user": {
            "id": user["id"],
            "name": user["full_name"],
            "email": user["email"],
            "picture": user.get("picture_url"),
            "role": user.get("role"),
        },
    }
