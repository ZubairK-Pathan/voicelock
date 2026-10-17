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

# ─── Environment & Authentication Configuration ──────────────────────────────

def load_voicelock_env() -> str:
    """Return runtime environment name: 'development', 'testing', or 'production'."""
    raw = os.getenv("VOICELOCK_ENV", "development").strip().lower()
    if raw in {"production", "testing", "development"}:
        return raw
    return "development"


def load_admin_emails() -> set[str]:
    """Return set of bootstrap admin email addresses from environment."""
    raw = os.getenv("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def load_admin_uids() -> set[str]:
    """Return set of bootstrap admin Firebase UIDs from environment."""
    raw = os.getenv("ADMIN_UIDS", "")
    return {u.strip() for u in raw.split(",") if u.strip()}


VOICELOCK_ENV = load_voicelock_env()
FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
ADMIN_EMAILS = load_admin_emails()
ADMIN_UIDS = load_admin_uids()

