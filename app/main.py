"""
app/main.py — FastAPI application factory and entry point.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.services.speaker_service import get_system


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm ML models and voiceprint profiles at startup."""
    get_system()
    yield


def create_app() -> FastAPI:
    """Create and configure the VoiceLock FastAPI application instance."""
    app = FastAPI(
        title="VoiceLock — Enterprise Speaker Recognition API",
        description="High-security speaker recognition and stateful anti-spoofing challenge-response verification.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register aggregate API routes
    app.include_router(api_router)

    return app


app = create_app()
