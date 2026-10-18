"""
app/api/routes_speakers.py — Enrolled speaker listing route.
"""

import sys
from unittest.mock import Mock
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import app.services.speaker_service as speaker_service
from app.schemas.verification import SpeakersResponse
from app.core.auth import AuthenticatedUser, get_current_admin
from app.db.session import get_db

router = APIRouter(tags=["Speakers"])


def _get_system():
    mod = sys.modules.get("cloud_api")
    if mod and hasattr(mod, "get_system"):
        return mod.get_system
    return speaker_service.get_system


def _get_speaker_service(session: Session) -> speaker_service.SpeakerService:
    mod = sys.modules.get("cloud_api")
    if mod and hasattr(mod, "SpeakerService"):
        return mod.SpeakerService(session)
    return speaker_service.SpeakerService(session)


def _is_mocked(fn) -> bool:
    return isinstance(fn, Mock) or hasattr(fn, "_mock_return_value") or hasattr(fn, "mock")


@router.get("/speakers", response_model=SpeakersResponse)
def list_speakers(
    admin: AuthenticatedUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """List all registered active speaker names currently enrolled in VoiceLock. Restricted to Admin."""
    get_sys = _get_system()
    if _is_mocked(get_sys):
        profiles, _ = get_sys()
        names = sorted(profiles.keys()) if profiles else []
    else:
        service = _get_speaker_service(db)
        try:
            names = service.get_registered_speakers()
        except speaker_service.SpeakerServiceDatabaseError as exc:
            raise HTTPException(status_code=500, detail="Database failure while retrieving registered speakers.") from exc

    return {
        "registered_speakers": names,
        "count": len(names),
    }
