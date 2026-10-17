"""
app/repositories/__init__.py — Repository package exports.
"""

from app.repositories.speaker_repository import (
    SpeakerRepository,
    SpeakerRepositoryError,
    DuplicateSpeakerError,
    SpeakerNotFoundError,
)

__all__ = [
    "SpeakerRepository",
    "SpeakerRepositoryError",
    "DuplicateSpeakerError",
    "SpeakerNotFoundError",
]
