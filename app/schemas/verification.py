"""
app/schemas/verification.py — Pydantic schemas for identification and verification endpoints.
"""

from typing import Optional
from pydantic import BaseModel, Field


class IdentifyResponse(BaseModel):
    predicted_speaker: str = Field(..., description="Name of the recognized speaker or 'Unknown'")
    similarity: float = Field(..., description="Cosine similarity score against closest enrolled voiceprint")
    is_unknown: bool = Field(..., description="Whether similarity was below acceptance threshold")
    all_scores: dict[str, float] = Field(..., description="Cosine similarity score for all enrolled speakers")
    threshold_used: float = Field(..., description="Server-enforced acceptance threshold")


class VerifyResponse(BaseModel):
    accepted: bool = Field(..., description="Whether verification succeeded")
    action: str = Field(..., description="'UNLOCK' if accepted, else 'DENY'")
    claimed_identity: str = Field(..., description="Name of speaker claimed")
    similarity: float = Field(..., description="Cosine similarity score against claimed voiceprint")
    threshold_used: float = Field(..., description="Server-enforced acceptance threshold")
    liveness_passed: bool = Field(..., description="Whether the spoken digit challenge passed")
    reason: Optional[str] = Field(None, description="Explanation message if verification failed")


class SpeakersResponse(BaseModel):
    registered_speakers: list[str] = Field(..., description="Alphabetical list of registered speaker names")
    count: int = Field(..., description="Total count of enrolled speakers")


class HealthResponse(BaseModel):
    status: str = Field(..., description="Service status ('online')")
    service: str = Field(..., description="Descriptive service name")
    version: str = Field(..., description="Service semantic version")
    threshold: Optional[float] = Field(None, description="Active server threshold (redacted in public health)")
    enrolled_speakers: Optional[int] = Field(None, description="Count of currently enrolled speaker voiceprints (redacted in public health)")
