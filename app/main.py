from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, journal, sessions, analytics, notifications
from app.config import settings

app = FastAPI(
    title="MindQueue API",
    description="Backend para la plataforma de salud mental MindQueue",
    version="1.0.0",
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,      prefix="/auth",      tags=["Autenticación"])
app.include_router(journal.router,   prefix="/journal",   tags=["Diario Emocional"])
app.include_router(sessions.router,  prefix="/sessions",  tags=["Sesiones"])
app.include_router(analytics.router,      prefix="/analytics",      tags=["Analytics"])
app.include_router(notifications.router,  prefix="/notifications",  tags=["Notificaciones"])

@app.get("/health", tags=["Sistema"])
def health_check():
    return {
        "status": "ok",
        "environment": settings.environment,
        "version": "1.0.0"
    }