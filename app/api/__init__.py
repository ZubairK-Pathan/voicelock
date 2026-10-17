"""
app/api/__init__.py — Aggregate API router for VoiceLock endpoints.
"""

from fastapi import APIRouter

from app.api.routes_health import router as health_router
from app.api.routes_speakers import router as speakers_router
from app.api.routes_challenges import router as challenges_router
from app.api.routes_verification import router as verification_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(speakers_router)
api_router.include_router(challenges_router)
api_router.include_router(verification_router)
