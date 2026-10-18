"""
app/db/__init__.py — Database package exports.
"""

from app.db.base import Base, SchemaInitialization, SpeakerRecord, UserSpeakerMapping, DeviceRecord
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
from app.db.session import (
    get_database_url,
    normalize_database_url,
    mask_database_url,
    create_db_engine,
    get_engine,
    get_session_factory,
    reset_engine,
    get_db,
    get_db_context,
)

__all__ = [
    "Base",
    "SchemaInitialization",
    "SpeakerRecord",
    "UserSpeakerMapping",
    "DeviceRecord",
    "SpeakerRepository",
    "SpeakerRepositoryError",
    "DuplicateSpeakerError",
    "SpeakerNotFoundError",
    "UserSpeakerRepository",
    "UserSpeakerRepositoryError",
    "DuplicateUserMappingError",
    "UserMappingNotFoundError",
    "get_database_url",
    "normalize_database_url",
    "mask_database_url",
    "create_db_engine",
    "get_engine",
    "get_session_factory",
    "reset_engine",
    "get_db",
    "get_db_context",
]
