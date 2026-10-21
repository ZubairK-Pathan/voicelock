"""
app/schemas/mapping.py — Pydantic schemas for administrator-managed user-to-speaker mappings.
Data minimization: Biometric embeddings, secret verifiers, and credentials are strictly excluded.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class CreateMappingRequest(BaseModel):
    """Payload for linking an authenticated Firebase user account to an enrolled voice identity."""
    firebase_uid: str = Field(..., min_length=1, max_length=128, description="Firebase Auth unique user identifier")
    speaker_id: str = Field(..., min_length=1, max_length=64, description="Enrolled speaker identity to bind")
    notes: Optional[str] = Field(None, max_length=500, description="Optional administrative notes")
    metadata_json: Optional[str] = Field(None, max_length=2000, description="Optional JSON metadata string")

    @field_validator("firebase_uid", "speaker_id")
    @classmethod
    def validate_non_whitespace(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field must not be empty or whitespace only.")
        return stripped


class UserSpeakerMappingItem(BaseModel):
    """Safe, UI-focused projection of a user-speaker mapping record."""
    id: int = Field(..., description="Unique mapping record primary key")
    firebase_uid: str = Field(..., description="Firebase Auth unique user identifier")
    speaker_id: str = Field(..., description="Enrolled speaker identity")
    assigned_by: Optional[str] = Field(None, description="Identifier of administrator who created the mapping")
    created_at: datetime = Field(..., description="Mapping creation timestamp (UTC)")
    updated_at: datetime = Field(..., description="Mapping last update timestamp (UTC)")
    speaker_name: Optional[str] = Field(None, description="Full display name of enrolled speaker if recorded")
    speaker_status: Optional[str] = Field(None, description="Current lifecycle status of the speaker (active, suspended, revoked)")
    sample_count: Optional[int] = Field(None, description="Number of enrolled audio samples for this speaker")


class MappingsListResponse(BaseModel):
    """Response containing list of all active user-speaker mappings."""
    mappings: List[UserSpeakerMappingItem] = Field(..., description="List of user-speaker mappings")
    count: int = Field(..., description="Total count of active mappings")


class UnmappedSpeakerItem(BaseModel):
    """Enrolled speaker eligible for mapping (active status and unassigned)."""
    speaker_id: str = Field(..., description="Unique enrolled speaker identity")
    full_name: Optional[str] = Field(None, description="Full display name of speaker if available")
    status: str = Field(..., description="Biometric registry lifecycle status")
    sample_count: int = Field(..., description="Enrolled sample count")
    created_at: datetime = Field(..., description="Enrollment registration timestamp (UTC)")


class UnmappedSpeakersResponse(BaseModel):
    """Response containing unmapped active enrolled speakers."""
    unmapped_speakers: List[UnmappedSpeakerItem] = Field(..., description="List of unmapped active speakers")
    count: int = Field(..., description="Total count of unmapped active speakers")


class MappingOperationResponse(BaseModel):
    """Result of an administrative mapping mutation (link / unlink)."""
    success: bool = Field(True, description="Whether the operation succeeded")
    message: str = Field(..., description="Descriptive status message")
    mapping: Optional[UserSpeakerMappingItem] = Field(None, description="The created or affected mapping record, if applicable")
