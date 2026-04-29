from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.services.onboarding import complete_onboarding, parse_onboarding_state
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

    Two flows share this endpoint:

      1. Web-first (default): exchange code → upsert user → issue JWT →
         frontend stores JWT and redirects to /app.

      2. Chat-first onboarding (state == 'onboard:tg:<token>'): exchange
         code → consume the onboarding token to bind the originating
         channel identifier (telegram_chat_id) to the matched/created
         user → push a welcome DM. Returns `{onboarded: true, channel: ...}`
         instead of a JWT so the frontend shows a "Return to Telegram"
         success page rather than redirecting into the SPA.
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

    # ----- Branch: chat-first onboarding -----
    onboarding = parse_onboarding_state(payload.state)
    if onboarding:
        channel, token = onboarding
        user = complete_onboarding(
            token=token,
            google_userinfo=user_info,
            access_token=access_token,
            encrypted_refresh_token=encrypted_rt,
        )
        if not user:
            raise HTTPException(
                status_code=400,
                detail="Onboarding token is invalid, expired, or already used.",
            )
        return {
            "message": "Onboarding complete",
            "onboarded": True,
            "channel": channel,
            "user": {
                "id": user["id"],
                "name": user.get("full_name"),
                "email": user["email"],
                "role": user.get("role"),
            },
        }

    # ----- Default: web-first OAuth (issue JWT) -----
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
