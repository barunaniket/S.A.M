from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.routes import auth

# Initialize the App
app = FastAPI(title="S.A.M. Faculty Platform", version="2.0")

# Enable CORS (Allows your React Frontend to talk to this Backend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)

# A simple Health Check endpoint
@app.get("/")
async def health_check():
    return {"status": "ok", "message": "S.A.M. API is running"}