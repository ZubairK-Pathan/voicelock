"""VoiceLock backend services."""
from app.services.speaker_service import (
    SpeakerService,
    SpeakerServiceError,
    SpeakerNotFoundError,
    InactiveSpeakerError,
    MissingSpeakerEmbeddingError,
    EmptySpeakerRegistryError,
    SpeakerServiceDatabaseError,
    get_system,
    reload_profiles,
    get_profiles,
    get_classifier,
    set_classifier_for_testing,
    reset_classifier_for_testing,
)
from app.services.challenge_service import get_challenge_store, default_challenge_store
from app.services.verification_service import save_upload

__all__ = [
    "SpeakerService",
    "SpeakerServiceError",
    "SpeakerNotFoundError",
    "InactiveSpeakerError",
    "MissingSpeakerEmbeddingError",
    "EmptySpeakerRegistryError",
    "SpeakerServiceDatabaseError",
    "get_system",
    "reload_profiles",
    "get_profiles",
    "get_classifier",
    "set_classifier_for_testing",
    "reset_classifier_for_testing",
    "get_challenge_store",
    "default_challenge_store",
    "save_upload",
]
