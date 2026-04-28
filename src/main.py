import uvicorn
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware

# Core utilities
from src.utils.middleware import verify_jwt_middleware

# Route modules
from src.api.routes import auth
from src.api import lifecycle_routes
from src.api.routes import (
    meetings,
    availability,
    agenda,
    process,
    notifications,
    email as email_routes,
    calendar as calendar_routes,
    analytics,
    ws_notifications,
    uploads,
    whatsapp,
    groups,
    health,
    me,
    timetable as timetable_routes,
    academic_calendar as academic_routes,
    tasks as tasks_routes,
    bookings as bookings_routes,
    admin_users as admin_users_routes,
    preferences as preferences_routes,
)

# ---------------------------------------------------------------------------
# App init
# ---------------------------------------------------------------------------
app = FastAPI(
    title="S.A.M. Faculty Platform",
    version="2.0",
    description="Smart Administrative Messenger — backend API for the faculty scheduling platform",
)

# ---------------------------------------------------------------------------
# Middleware (order matters: CORS first, then JWT)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(BaseHTTPMiddleware, dispatch=verify_jwt_middleware)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth.router)                                         # /auth/*
app.include_router(lifecycle_routes.router, prefix="/api/v1/experimental", tags=["Lifecycle"])
app.include_router(meetings.router,       prefix="/api/v1", tags=["Meetings"])
app.include_router(availability.router,   prefix="/api/v1", tags=["Availability"])
app.include_router(agenda.router,         prefix="/api/v1", tags=["Agenda"])
app.include_router(process.router,        prefix="/api/v1", tags=["LLM Processing"])
app.include_router(notifications.router,  prefix="/api/v1", tags=["Notifications"])
app.include_router(email_routes.router,   prefix="/api/v1", tags=["Email"])
app.include_router(calendar_routes.router,   prefix="/api/v1", tags=["Calendar Sync"])
app.include_router(analytics.router,         prefix="/api/v1", tags=["Analytics"])
app.include_router(ws_notifications.router,  prefix="/api/v1", tags=["WebSocket"])
app.include_router(uploads.router,            prefix="/api/v1", tags=["Uploads"])
app.include_router(groups.router,             prefix="/api/v1", tags=["Groups"])
app.include_router(whatsapp.router,                              tags=["WhatsApp Webhook"])  # mounted at /webhooks/whatsapp
app.include_router(health.router,             prefix="/api/v1", tags=["Health"])
app.include_router(me.router,                  prefix="/api/v1", tags=["Me"])
app.include_router(timetable_routes.router,    prefix="/api/v1", tags=["Timetable"])
app.include_router(academic_routes.router,     prefix="/api/v1", tags=["Academic Calendar"])
app.include_router(tasks_routes.router,        prefix="/api/v1", tags=["Tasks"])
app.include_router(bookings_routes.router,     prefix="/api/v1", tags=["Bookings"])
app.include_router(admin_users_routes.router,  prefix="/api/v1", tags=["Admin Users"])
app.include_router(preferences_routes.router,  prefix="/api/v1", tags=["Preferences"])

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
security = HTTPBearer()

@app.get("/", tags=["Health"])
async def health_check():
    return {"status": "ok", "message": "S.A.M. API is running"}


@app.get("/api/test-secure", tags=["Health"], dependencies=[Depends(security)])
async def test_secure_endpoint(request: Request):
    return {
        "status": "Authorized",
        "user_id": request.state.user_id,
        "org_id": request.state.org_id,
        "message": "JWT validated successfully",
    }


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
