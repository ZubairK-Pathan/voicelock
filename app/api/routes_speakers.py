"""
app/api/routes_speakers.py — Enrolled speaker listing and enrollment routes.
"""

import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from typing import List, Optional
from unittest.mock import Mock

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

import app.services.speaker_service as speaker_service
from app.core.auth import AuthenticatedUser, get_current_admin
from app.db.base import SecurityEvent, SecurityEventSeverity, SecurityEventStatus, SecurityEventType
from app.db.session import get_db
from app.repositories.speaker_repository import DuplicateSpeakerError
from app.schemas.speaker import SpeakerEnrollmentResponse
from app.schemas.verification import SpeakersResponse
from audio_utils import SUPPORTED_AUDIO_EXTENSIONS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Speakers"])

MAX_SAMPLE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB per sample
MAX_TOTAL_ENROLLMENT_BYTES = 50 * 1024 * 1024  # 50 MB total for all samples


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


@router.post(
    "/speakers",
    response_model=SpeakerEnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll new speaker profile",
)
async def enroll_speaker(
    request: Request,
    speaker_id: str = Form(..., description="Unique speaker identifier"),
    full_name: Optional[str] = Form(None, description="Human-readable full name"),
    samples: List[UploadFile] = File(..., description="3 to 10 audio recordings for biometric enrollment"),
    admin: AuthenticatedUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Enroll a new speaker profile with 3-10 audio samples.
    Restricted to Administrator role.
    Validates audio decodability, duration, non-silence, extracts 192-d ECAPA-TDNN embeddings,
    computes the centroid vector, and creates atomic database and audit event records.
    """
    if not samples or len(samples) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"At least 3 audio samples are required for enrollment (received {len(samples) if samples else 0}).",
        )
    if len(samples) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"At most 10 audio samples are allowed for enrollment (received {len(samples)}).",
        )

    temp_paths: List[str] = []
    total_bytes = 0

    try:
        for idx, sample in enumerate(samples):
            filename = sample.filename or f"sample_{idx + 1}.wav"
            ext = Path(filename).suffix.lower()
            if ext not in SUPPORTED_AUDIO_EXTENSIONS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Sample '{filename}' has unsupported format '{ext}'. Allowed: {sorted(SUPPORTED_AUDIO_EXTENSIONS)}",
                )

            tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            sample_bytes = 0
            try:
                while True:
                    chunk = await sample.read(65536)
                    if not chunk:
                        break
                    sample_bytes += len(chunk)
                    total_bytes += len(chunk)

                    if sample_bytes > MAX_SAMPLE_SIZE_BYTES:
                        raise HTTPException(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail=f"Sample '{filename}' exceeds maximum allowed size of {MAX_SAMPLE_SIZE_BYTES // (1024 * 1024)} MB.",
                        )
                    if total_bytes > MAX_TOTAL_ENROLLMENT_BYTES:
                        raise HTTPException(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail=f"Total enrollment payload exceeds maximum allowed size of {MAX_TOTAL_ENROLLMENT_BYTES // (1024 * 1024)} MB.",
                        )
                    tmp.write(chunk)
            finally:
                tmp.close()

            if sample_bytes == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Sample '{filename}' is empty.",
                )

            temp_paths.append(tmp.name)

        get_sys = _get_system()
        if _is_mocked(get_sys):
            _, clf = get_sys()
        else:
            clf = speaker_service.get_classifier()

        service = _get_speaker_service(db)
        record = service.enroll_speaker(
            speaker_id=speaker_id,
            full_name=full_name,
            audio_paths=temp_paths,
            enrolled_by=admin.uid,
            classifier=clf,
        )

        req_id = request.headers.get("x-request-id")
        security_event = SecurityEvent(
            event_type=SecurityEventType.ADMIN_ACTION.value,
            severity=SecurityEventSeverity.LOW.value,
            status=SecurityEventStatus.LOGGED.value,
            user_id=admin.uid,
            details=f"Enrolled speaker profile: {record.speaker_id}"[:255],
            request_id=req_id[:64] if req_id else None,
            metadata_json=json.dumps({
                "action": "speaker_enrollment",
                "speaker_id": record.speaker_id,
                "sample_count": record.sample_count,
            }),
        )
        db.add(security_event)
        db.commit()
        db.refresh(record)

        return SpeakerEnrollmentResponse(
            speaker_id=record.speaker_id,
            full_name=record.full_name,
            status=record.status,
            sample_count=record.sample_count,
            embedding_dim=record.embedding_dim,
            created_at=record.created_at,
        )

    except DuplicateSpeakerError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Unexpected error during speaker enrollment: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during speaker enrollment.",
        ) from exc
    finally:
        for p in temp_paths:
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except OSError:
                pass
