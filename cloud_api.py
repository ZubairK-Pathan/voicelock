#!/usr/bin/env python3
"""
cloud_api.py — Backward-compatible FastAPI entry point for VoiceLock Enterprise.

This module preserves the legacy entry point for running VoiceLock via:
    uvicorn cloud_api:app --host 0.0.0.0 --port 8000

The application logic has been incrementally modularized into the `app/` package:
    - app/core/config.py: Server threshold and upload size limits
    - app/core/errors.py: Reusable HTTP exceptions
    - app/schemas/: Pydantic data models for challenges and verification
    - app/services/: ECAPA-TDNN model caching, liveness challenge store, and upload streaming
    - app/api/: Modular route controllers (health, speakers, challenges, verification)
    - app/main.py: FastAPI application factory

All public constants, functions, and services are re-exported here for complete
backward compatibility with existing scripts, integrations, and automated tests.
"""

import uvicorn

# Re-export core configuration and loaders
from app.core.config import (
    SERVER_THRESHOLD,
    MAX_AUDIO_SIZE_BYTES,
    ALLOWED_EXTENSIONS,
    load_server_threshold,
    load_max_audio_size,
    DEFAULT_CHALLENGE_TTL_SECONDS,
    DEFAULT_CHALLENGE_LENGTH,
)

# Re-export ML inference functions and defaults
from predict import (
    predict_speaker,
    verify_speaker,
    DEFAULT_THRESHOLD,
)

# Re-export speaker service singletons
from app.services.speaker_service import (
    get_system,
    reload_profiles,
    get_profiles,
    get_classifier,
)

# Re-export upload streaming service
from app.services.verification_service import save_upload

# Re-export liveness challenge store and verification
from app.services.challenge_service import (
    get_challenge_store,
    default_challenge_store,
    challenge_display,
    challenge_expected_words,
    run_liveness_check,
    BaseChallengeStore,
    InMemoryChallengeStore,
    LivenessChallenge,
    ChallengeStatus,
    generate_challenge,
)

# Re-export application instance and factory
from app.main import app, create_app

__all__ = [
    "app",
    "create_app",
    "SERVER_THRESHOLD",
    "MAX_AUDIO_SIZE_BYTES",
    "ALLOWED_EXTENSIONS",
    "load_server_threshold",
    "load_max_audio_size",
    "predict_speaker",
    "verify_speaker",
    "DEFAULT_THRESHOLD",
    "get_system",
    "reload_profiles",
    "get_profiles",
    "get_classifier",
    "save_upload",
    "get_challenge_store",
    "default_challenge_store",
    "challenge_display",
    "challenge_expected_words",
    "run_liveness_check",
    "BaseChallengeStore",
    "InMemoryChallengeStore",
    "LivenessChallenge",
    "ChallengeStatus",
    "generate_challenge",
]

if __name__ == "__main__":
    uvicorn.run("cloud_api:app", host="0.0.0.0", port=8000, reload=False)
