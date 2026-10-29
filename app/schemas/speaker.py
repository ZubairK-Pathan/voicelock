"""
app/schemas/speaker.py — Pydantic schemas for speaker registry and enrollment operations.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class SpeakerEnrollmentResponse(BaseModel):
    """Structured response confirming persistent speaker enrollment."""
    speaker_id: str = Field(..., description="Canonical unique speaker identifier")
    full_name: Optional[str] = Field(None, description="Human display name")
    status: str = Field("active", description="Enrollment lifecycle status")
    sample_count: int = Field(..., description="Number of audio samples averaged into profile")
    embedding_dim: int = Field(192, description="Dimensionality of the persisted biometric voiceprint")
    created_at: datetime = Field(..., description="ISO 8601 UTC creation timestamp")
