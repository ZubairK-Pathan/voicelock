"""
app/db/__init__.py — Database package exports.
"""

from app.db.base import (
    Base,
    SchemaInitialization,
    SpeakerRecord,
    UserSpeakerMapping,
    DeviceRecord,
    VerificationOutcome,
    VALID_VERIFICATION_OUTCOMES,
    VALID_VERIFICATION_FLOWS,
    VerificationEvent,
    SecurityEventSeverity,
    SecurityEventStatus,
    SecurityEventType,
    VALID_SECURITY_EVENT_SEVERITIES,
    VALID_SECURITY_EVENT_STATUSES,
    VALID_SECURITY_EVENT_TYPES,
    SecurityEvent,
)
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
    "VerificationOutcome",
    "VALID_VERIFICATION_OUTCOMES",
    "VALID_VERIFICATION_FLOWS",
    "VerificationEvent",
    "SecurityEventSeverity",
    "SecurityEventStatus",
    "SecurityEventType",
    "VALID_SECURITY_EVENT_SEVERITIES",
    "VALID_SECURITY_EVENT_STATUSES",
    "VALID_SECURITY_EVENT_TYPES",
    "SecurityEvent",
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
