from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, journal, sessions, analytics
from app.config import settings

app = FastAPI(
    title="MindQueue API",
    version="1.0.0",
    docs_url="/docs" if settings.environment == "development" else None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,      prefix="/auth",      tags=["auth"])
app.include_router(journal.router,   prefix="/journal",   tags=["journal"])
app.include_router(sessions.router,  prefix="/sessions",  tags=["sessions"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])

@app.get("/health")
def health():
    return {"status": "ok", "env": settings.environment}