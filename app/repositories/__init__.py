"""
app/repositories/__init__.py — Repository package exports.
"""

from app.repositories.speaker_repository import (
    SpeakerRepository,
    SpeakerRepositoryError,
    DuplicateSpeakerError,
    SpeakerNotFoundError,
)
from app.repositories.user_speaker_repository import (
    UserSpeakerRepository,
    UserSpeakerRepositoryError,
    DuplicateUserMappingError,
    UserMappingNotFoundError,
)

__all__ = [
    "SpeakerRepository",
    "SpeakerRepositoryError",
    "DuplicateSpeakerError",
    "SpeakerNotFoundError",
    "UserSpeakerRepository",
    "UserSpeakerRepositoryError",
    "DuplicateUserMappingError",
    "UserMappingNotFoundError",
]

