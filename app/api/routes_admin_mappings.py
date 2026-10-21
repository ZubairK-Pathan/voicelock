"""
app/api/routes_admin_mappings.py — Administrator-managed user-to-speaker identity mapping routes.

Secured strictly with Firebase token verification and get_current_admin authorization (RBAC).
Never trusts client-supplied admin flags or query parameters.
Data minimization: Biometric embeddings, raw audio, and sensitive secrets are strictly excluded.
Audit trail: Successful linking and unlinking operations record a SecurityEvent within the same transaction.
"""

import json
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedUser, get_current_admin
from app.db.base import (
    SecurityEvent,
    SecurityEventType,
    SecurityEventSeverity,
    SecurityEventStatus,
)
from app.db.session import get_db
from app.repositories.speaker_repository import SpeakerRepository
from app.repositories.user_speaker_repository import (
    UserSpeakerRepository,
    DuplicateUserMappingError,
)
from app.schemas.mapping import (
    CreateMappingRequest,
    UserSpeakerMappingItem,
    MappingsListResponse,
    UnmappedSpeakerItem,
    UnmappedSpeakersResponse,
    MappingOperationResponse,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/admin/mappings", tags=["Admin Mappings"])


def _map_to_item(m) -> UserSpeakerMappingItem:
    """Helper to convert ORM UserSpeakerMapping entity to UI-safe Pydantic item."""
    spk = m.speaker
    return UserSpeakerMappingItem(
        id=m.id,
        firebase_uid=m.firebase_uid,
        speaker_id=m.speaker_id,
        assigned_by=m.assigned_by,
        created_at=m.created_at,
        updated_at=m.updated_at,
        speaker_name=spk.full_name if spk else None,
        speaker_status=spk.status if spk else None,
        sample_count=spk.sample_count if spk else None,
    )


@router.get("", response_model=MappingsListResponse)
@router.get("/", response_model=MappingsListResponse, include_in_schema=False)
def list_mappings(
    admin: AuthenticatedUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    List all active user-to-speaker mappings with speaker details.
    Restricted strictly to administrators with verified non-revoked session.
    """
    user_repo = UserSpeakerRepository(db)
    try:
        mappings = user_repo.list_mappings()
    except Exception as exc:
        logger.error("Failed to query user-speaker mappings: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Database failure while querying user-speaker mappings.",
        ) from exc

    items = [_map_to_item(m) for m in mappings]
    return MappingsListResponse(
        mappings=items,
        count=len(items),
    )


@router.get("/unmapped-speakers", response_model=UnmappedSpeakersResponse)
def list_unmapped_speakers(
    admin: AuthenticatedUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    List all enrolled speakers eligible for mapping (active status and not yet assigned to any user).
    Restricted strictly to administrators with verified non-revoked session.
    """
    speaker_repo = SpeakerRepository(db)
    try:
        speakers = speaker_repo.get_unmapped_active_speakers()
    except Exception as exc:
        logger.error("Failed to query unmapped speakers: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Database failure while querying unmapped speakers.",
        ) from exc

    items = [
        UnmappedSpeakerItem(
            speaker_id=s.speaker_id,
            full_name=s.full_name,
            status=s.status,
            sample_count=s.sample_count,
            created_at=s.created_at,
        )
        for s in speakers
    ]
    return UnmappedSpeakersResponse(
        unmapped_speakers=items,
        count=len(items),
    )


@router.post("", response_model=MappingOperationResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=MappingOperationResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_mapping(
    payload: CreateMappingRequest,
    admin: AuthenticatedUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Link a Firebase user account to an enrolled speaker identity.
    Validates speaker existence and active status.
    Enforces 1-to-1 cardinality (rejects duplicate UID or duplicate speaker with HTTP 409).
    Audits the administrative action in security_events atomically in the same transaction.
    """
    clean_uid = payload.firebase_uid.strip()
    clean_speaker = payload.speaker_id.strip()

    speaker_repo = SpeakerRepository(db)
    user_repo = UserSpeakerRepository(db)

    try:
        # 1. Validate speaker exists
        speaker = speaker_repo.get_by_speaker_id(clean_speaker)
        if speaker is None:
            raise HTTPException(
                status_code=404,
                detail=f"Speaker '{clean_speaker}' not found in registry.",
            )

        # 2. Validate speaker is active
        if not speaker.is_active:
            raise HTTPException(
                status_code=400,
                detail=f"Speaker '{clean_speaker}' is not active (status: '{speaker.status}'). Cannot map inactive or suspended speaker.",
            )

        # 3. Check for existing mapping conflicts
        existing_for_user = user_repo.get_by_firebase_uid(clean_uid)
        if existing_for_user is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Firebase UID '{clean_uid}' is already mapped to speaker '{existing_for_user.speaker_id}'. Each account may have at most one active speaker identity.",
            )

        existing_for_speaker = user_repo.get_by_speaker_id(clean_speaker)
        if existing_for_speaker is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Speaker '{clean_speaker}' is already assigned to account '{existing_for_speaker.firebase_uid}'. A speaker identity cannot be assigned to multiple accounts.",
            )

        # 4. Construct metadata
        metadata = payload.metadata_json
        if not metadata and payload.notes:
            metadata = json.dumps({"notes": payload.notes})

        # 5. Create mapping record within transaction
        mapping = user_repo.create(
            firebase_uid=clean_uid,
            speaker_id=clean_speaker,
            assigned_by=admin.uid,
            metadata_json=metadata,
        )

        # 6. Record administrative audit event within the SAME transaction
        audit_metadata = json.dumps({
            "action": "link_user_speaker",
            "firebase_uid": clean_uid,
            "speaker_id": clean_speaker,
            "mapping_id": mapping.id,
        })
        audit_event = SecurityEvent(
            event_type=SecurityEventType.ADMIN_ACTION.value,
            severity=SecurityEventSeverity.LOW.value,
            status=SecurityEventStatus.LOGGED.value,
            user_id=admin.uid,
            details=f"Linked user '{clean_uid}' to speaker '{clean_speaker}'",
            metadata_json=audit_metadata,
        )
        db.add(audit_event)
        db.flush()

        # 7. Commit both atomically
        db.commit()
        db.refresh(mapping)

        return MappingOperationResponse(
            success=True,
            message=f"Successfully linked account '{clean_uid}' to speaker identity '{clean_speaker}'.",
            mapping=_map_to_item(mapping),
        )

    except HTTPException:
        db.rollback()
        raise
    except DuplicateUserMappingError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.error("Failed to link user speaker mapping: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Database failure while linking user identity to speaker.",
        ) from exc


@router.delete("/{mapping_id}", response_model=MappingOperationResponse)
def delete_mapping(
    mapping_id: int,
    admin: AuthenticatedUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Unlink a user-speaker mapping by its primary key identifier.
    Deletes ONLY the mapping row. Never deletes the speaker record, embedding, or audio data.
    Audits the administrative action in security_events atomically in the same transaction.
    """
    user_repo = UserSpeakerRepository(db)

    try:
        mapping = user_repo.get_by_id(mapping_id)
        if mapping is None:
            raise HTTPException(
                status_code=404,
                detail=f"User-speaker mapping {mapping_id} not found.",
            )

        deleted_uid = mapping.firebase_uid
        deleted_speaker_id = mapping.speaker_id

        # 1. Delete mapping record
        db.delete(mapping)
        db.flush()

        # 2. Record administrative audit event in the same transaction
        audit_metadata = json.dumps({
            "action": "unlink_user_speaker",
            "firebase_uid": deleted_uid,
            "speaker_id": deleted_speaker_id,
            "mapping_id": mapping_id,
        })
        audit_event = SecurityEvent(
            event_type=SecurityEventType.ADMIN_ACTION.value,
            severity=SecurityEventSeverity.LOW.value,
            status=SecurityEventStatus.LOGGED.value,
            user_id=admin.uid,
            details=f"Unlinked user '{deleted_uid}' from speaker '{deleted_speaker_id}'",
            metadata_json=audit_metadata,
        )
        db.add(audit_event)
        db.flush()

        # 3. Commit both atomically
        db.commit()

        return MappingOperationResponse(
            success=True,
            message=f"Successfully unlinked account '{deleted_uid}' from speaker identity '{deleted_speaker_id}'.",
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Failed to unlink user speaker mapping: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Database failure while unlinking user identity.",
        ) from exc
