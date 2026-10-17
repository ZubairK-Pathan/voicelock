"""
app/api/routes_speakers.py — Enrolled speaker listing route.
"""

import sys
from fastapi import APIRouter
import app.services.speaker_service as speaker_service
from app.schemas.verification import SpeakersResponse

router = APIRouter(tags=["Speakers"])


def _get_system():
    mod = sys.modules.get("cloud_api")
    if mod and hasattr(mod, "get_system"):
        return mod.get_system
    return speaker_service.get_system


@router.get("/speakers", response_model=SpeakersResponse)
def list_speakers():
    """List all registered speaker names currently enrolled in VoiceLock."""
    get_sys = _get_system()
    profiles, _ = get_sys()
    names = sorted(profiles.keys()) if profiles else []
    return {
        "registered_speakers": names,
        "count": len(names),
    }

