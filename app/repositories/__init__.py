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
from app.repositories.device_repository import (
    DeviceRepository,
    DeviceRepositoryError,
    DuplicateDeviceError,
    DeviceNotFoundError,
)
from app.repositories.verification_event_repository import (
    VerificationEventRepository,
    VerificationEventRepositoryError,
    VerificationEventNotFoundError,
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
    "DeviceRepository",
    "DeviceRepositoryError",
    "DuplicateDeviceError",
    "DeviceNotFoundError",
    "VerificationEventRepository",
    "VerificationEventRepositoryError",
    "VerificationEventNotFoundError",
]

