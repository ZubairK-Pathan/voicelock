"""
app/core/config.py — Centralized configuration and security defaults for VoiceLock.
"""

import os
from pathlib import Path
from predict import DEFAULT_THRESHOLD

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def load_env_files() -> None:
    """
    Load environment variables from local .env and .env.local files if present,
    without overwriting variables already explicitly set in os.environ.
    During automated unit test runs (e.g. pytest), automatic file loading is skipped
    to ensure test suites remain isolated and do not mutate remote databases.
    """
    import sys
    if "pytest" in sys.modules or os.getenv("VOICELOCK_ENV") == "testing":
        return

    for fname in (".env", ".env.local"):
        env_path = BASE_DIR / fname
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
            except Exception:
                pass


load_env_files()


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
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".webm"}

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
FIREBASE_CREDENTIALS_JSON = os.getenv("FIREBASE_CREDENTIALS_JSON")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
ADMIN_EMAILS = load_admin_emails()
ADMIN_UIDS = load_admin_uids()
TRUST_TOKEN_ADMIN_CLAIMS = os.getenv("TRUST_TOKEN_ADMIN_CLAIMS", "true" if VOICELOCK_ENV != "production" else "false").lower() in ("true", "1")

# ─── CORS Configuration ───────────────────────────────────────────────────────

def load_allowed_cors_origins() -> list[str]:
    """
    Load and validate allowed CORS origins.
    Development defaults: standard local ports (3000, 5173, 8501).
    Production: Loaded from ALLOWED_CORS_ORIGINS environment variable.
    Rejects wildcard '*' when credentials are enabled (prohibited by CORS spec).
    """
    raw = os.getenv("ALLOWED_CORS_ORIGINS", "")
    if raw.strip():
        origins = [orig.strip() for orig in raw.split(",") if orig.strip()]
        if "*" in origins:
            raise ValueError("Wildcard CORS origin '*' is strictly prohibited when credentials are enabled.")
        return origins
    current_env = os.getenv("VOICELOCK_ENV", VOICELOCK_ENV).strip().lower()
    if current_env == "production":
        return []
    return [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8501",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8501",
    ]


# ─── IoT Device Security Configuration ────────────────────────────────────────

MAX_TIMESTAMP_DRIFT_SECONDS = 300  # 5 minutes tolerance window for HMAC timestamps
MAX_CONCURRENT_INFERENCES = 4      # Prevent CPU core starvation from parallel ECAPA-TDNN feature extractions

def load_device_key_fallback_enabled() -> bool:
    """
    Control whether static X-Device-Key authentication fallback is permitted.
    Defaults to True in development/testing, strictly False in production.
    """
    current_env = os.getenv("VOICELOCK_ENV", VOICELOCK_ENV).strip().lower()
    raw = os.getenv("VOICELOCK_ENABLE_DEVICE_KEY_FALLBACK")
    if raw is not None:
        return raw.strip().lower() in ("true", "1", "yes")
    return current_env != "production"


ENABLE_DEVICE_KEY_FALLBACK = load_device_key_fallback_enabled()


def load_device_registry() -> dict[str, dict]:
    """
    Load registered hardware devices from environment variable DEVICE_REGISTRY_JSON.
    Returns mapping: {device_id: {"secret": "...", "name": "..."}}
    """
    import json
    raw = os.getenv("DEVICE_REGISTRY_JSON", "")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw.strip())
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}



