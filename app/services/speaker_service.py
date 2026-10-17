"""
app/services/speaker_service.py — Singleton management for SpeechBrain ECAPA-TDNN model and speaker profiles.
"""

from typing import Optional
from audio_utils import load_embedding_model, load_profiles

_profiles: Optional[dict] = None
_classifier = None


def get_system():
    """
    Return cached (profiles_dict, embedding_classifier) tuple.
    Loads SpeechBrain ECAPA-TDNN model and voiceprint embeddings once at startup.
    Avoids duplicate in-memory initialization.
    """
    global _profiles, _classifier
    if _classifier is None:
        _classifier = load_embedding_model()
    if _profiles is None:
        _profiles = load_profiles()
    return _profiles, _classifier


def reload_profiles() -> dict:
    """Reload speaker profiles from disk (e.g. after a new enrollment)."""
    global _profiles
    _profiles = load_profiles()
    return _profiles


def get_profiles() -> dict:
    """Return enrolled speaker profiles dictionary."""
    profiles, _ = get_system()
    return profiles


def get_classifier():
    """Return the cached SpeechBrain embedding classifier instance."""
    _, classifier = get_system()
    return classifier
