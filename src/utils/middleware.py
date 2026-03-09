import os
import jwt
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

async def verify_jwt_middleware(request: Request, call_next):
    excluded_paths = {"/docs", "/openapi.json", "/api/auth/login", "/api/auth/google"}
    
    if request.url.path in excluded_paths:
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

        user_id: str = payload.get("user_id")
        org_id: str = payload.get("org_id")

        if user_id is None or org_id is None:
            raise ValueError("Token missing critical identity claims")

        request.state.user_id = user_id
        request.state.org_id = org_id

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

    response = await call_next(request)
    return response