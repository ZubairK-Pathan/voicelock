"""
app/schemas/challenge.py — Pydantic schemas for liveness challenge endpoints.
"""

from typing import Optional
from pydantic import BaseModel, Field


class ChallengeRequest(BaseModel):
    claimed_identity: Optional[str] = Field(None, description="Optional claimed speaker name to bind to the challenge")
    session_id: Optional[str] = Field(None, description="Optional existing session ID; if omitted, a new one is issued")


class ChallengeResponse(BaseModel):
    challenge_id: str = Field(..., description="Unique cryptographically generated challenge identifier")
    session_id: str = Field(..., description="Session identifier bound to this challenge")
    claimed_identity: Optional[str] = Field(None, description="Speaker name bound to the challenge, if specified")
    digits: list[str] = Field(..., description="Random sequence of digits the user must speak")
    display: str = Field(..., description="Formatted string for user display")
    expires_at: float = Field(..., description="Unix timestamp of challenge expiration")
    expires_in_seconds: int = Field(60, description="Remaining validity window in seconds")
