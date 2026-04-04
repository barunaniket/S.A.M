import uvicorn
from fastapi import FastAPI, Depends, Request  # <--- Added 'Request' here
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer 

# Import your routes and the new middleware
from src.api.routes import auth
from src.utils.middleware import verify_jwt_middleware

# Initialize the App
app = FastAPI(title="S.A.M. Faculty Platform", version="2.0")

# 1. REGISTER THE MIDDLEWARE
app.middleware("http")(verify_jwt_middleware)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(
    lifecycle_routes.router,
    prefix="/api/v1/experimental",
    tags=["Lifecycle Validation"]
)
app.include_router(auth.router)

# 2. ADD SWAGGER UI SECURITY SCHEME
security = HTTPBearer()

@app.get("/")
async def health_check():
    return {"status": "ok", "message": "S.A.M. API is running"}

# 3. ADD A PROTECTED TEST ROUTE
@app.get("/api/test-secure", dependencies=[Depends(security)])
async def test_secure_endpoint(request: Request): 
    # If the middleware works, this code ONLY runs if the token is valid.
    return {
        "status": "Authorized",
        "user_id": request.state.user_id,
        "org_id": request.state.org_id,
        "message": "You have successfully passed the Gatekeeper!"
    }

if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)