"""
app/api/routes_health.py — Health and discovery endpoint.
"""

import sys
from fastapi import APIRouter
from app.core.config import SERVER_THRESHOLD
import app.services.speaker_service as speaker_service
from app.schemas.verification import HealthResponse

router = APIRouter(tags=["Health"])


def _get_system():
    mod = sys.modules.get("cloud_api")
    if mod and hasattr(mod, "get_system"):
        return mod.get_system
    return speaker_service.get_system


@router.get("/", response_model=HealthResponse)
def root():
    """Service health check and basic system capabilities discovery."""
    get_sys = _get_system()
    profiles, _ = get_sys()
    return {
        "status": "online",
        "service": "VoiceLock — Speaker Recognition API",
        "version": "1.0.0",
        "threshold": SERVER_THRESHOLD,
        "enrolled_speakers": len(profiles) if profiles else 0,
    }

