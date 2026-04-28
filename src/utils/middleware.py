import jwt
from fastapi import Request, status
from fastapi.responses import JSONResponse
from src.utils.config_loader import Config

SECRET_KEY = Config.SECRET_KEY
ALGORITHM = Config.ALGORITHM

# Paths that never require a JWT — prefix match.
# NOTE: do NOT add "/" here — every path starts with "/", which would
# silently bypass auth for the entire API. The exact-match "/" health check
# is handled in _is_excluded below.
_EXCLUDED_PREFIXES = (
    "/docs",
    "/openapi.json",
    "/redoc",
    "/auth/",          # all /auth/* endpoints (login-url, callback)
    "/webhooks/",      # provider webhooks — verified per-provider, not via JWT
)


def _is_excluded(path: str) -> bool:
    if path == "/" or path == "/api/v1/health":
        return True
    for prefix in _EXCLUDED_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


async def verify_jwt_middleware(request: Request, call_next):
    # CORS preflight carries no Authorization header — let it through so the
    # CORSMiddleware downstream can answer it with the right headers.
    if request.method == "OPTIONS":
        return await call_next(request)

    if _is_excluded(request.url.path):
        return await call_next(request)

    auth_header = request.headers.get("Authorization")

    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Missing or invalid Authorization header"}
        )

    try:
        token = auth_header.split(" ")[1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        user_id = payload.get("user_id")
        org_id = payload.get("org_id")

        if user_id is None or org_id is None:
            raise ValueError("Token missing required identity claims (user_id, org_id)")

        request.state.user_id = user_id
        request.state.org_id = org_id
        request.state.email = payload.get("email")  # optional, set if present in JWT
        request.state.role = payload.get("role")    # optional; consumed by require_roles()

    except jwt.ExpiredSignatureError:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Token has expired"}
        )
    except (jwt.InvalidTokenError, ValueError) as e:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": f"Invalid authentication credentials: {str(e)}"}
        )

    return await call_next(request)
