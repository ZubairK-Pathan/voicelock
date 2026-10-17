"""
app/core/config.py — Centralized configuration and security defaults for VoiceLock.
"""

import os
from pathlib import Path
from predict import DEFAULT_THRESHOLD

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def load_server_threshold() -> float:
    """
    Load and validate the server-side acceptance threshold.
    Guarantees a valid float bounded in [0.0, 1.0].
    Defaults safely to DEFAULT_THRESHOLD (0.25) if invalid or absent.
    """
    raw = os.getenv("DEFAULT_THRESHOLD")
    if raw is None or not raw.strip():
        return DEFAULT_THRESHOLD
    try:
        val = float(raw.strip())
        if 0.0 <= val <= 1.0:
            return val
    except (ValueError, TypeError):
        pass
    return DEFAULT_THRESHOLD


def load_max_audio_size() -> int:
    """
    Load and validate the maximum allowed upload size in bytes.
    Defaults to 10 MB (10,485,760 bytes) if invalid or absent.
    """
    default_size = 10 * 1024 * 1024  # 10 MB
    raw = os.getenv("MAX_AUDIO_SIZE_BYTES")
    if raw is None or not raw.strip():
        return default_size
    try:
        val = int(raw.strip())
        if val > 0:
            return val
    except (ValueError, TypeError):
        pass
    return default_size


SERVER_THRESHOLD = load_server_threshold()
MAX_AUDIO_SIZE_BYTES = load_max_audio_size()
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}

DEFAULT_CHALLENGE_TTL_SECONDS = 60
DEFAULT_CHALLENGE_LENGTH = 3
