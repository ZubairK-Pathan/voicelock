"""
app/api/__init__.py — Aggregate API router for VoiceLock endpoints.
"""

from fastapi import APIRouter

from app.api.routes_health import router as health_router
from app.api.routes_speakers import router as speakers_router
from app.api.routes_challenges import router as challenges_router
from app.api.routes_verification import router as verification_router
from app.api.routes_devices import router as devices_router
from app.api.routes_metrics import router as metrics_router
from app.api.routes_admin_mappings import router as admin_mappings_router
from app.api.routes_security_events import router as security_events_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(speakers_router)
api_router.include_router(devices_router)
api_router.include_router(challenges_router)
api_router.include_router(verification_router)
api_router.include_router(metrics_router)
api_router.include_router(admin_mappings_router)
api_router.include_router(security_events_router)
