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

# Re-export authentication and authorization utilities
from app.core.auth import (
    AuthenticatedUser,
    get_current_user,
    get_current_admin,
    require_permission,
    authenticate_ws_admin,
    verify_firebase_id_token,
    set_test_token_verifier,
    get_firebase_app,
)
from app.core.auth_policy import (
    IdentityType,
    Role,
    AuthScheme,
    Permission,
    ROLE_PERMISSIONS,
    EndpointPolicy,
    ENDPOINT_POLICIES,
    has_permission,
    get_endpoint_policy,
    is_public_endpoint,
)

# Re-export device authentication and actor resolution
from app.core.device_auth import (
    AuthenticatedDevice,
    get_current_device,
    get_current_actor,
    resolve_user_voice_identity,
    check_verification_authorization,
    set_test_device_registry,
    get_nonce_store,
    InMemoryNonceStore,
)

# Re-export middleware and rate limiting
from app.core.middleware import (
    RequestSizeLimiterMiddleware,
    PayloadTooLargeError,
)
from app.core.rate_limit import (
    InMemoryRateLimiter,
    enforce_rate_limit,
    get_actor_rate_key,
    acquire_inference_slot,
    release_inference_slot,
)
from app.core.config import (
    load_allowed_cors_origins,
    load_device_registry,
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
    "AuthenticatedUser",
    "get_current_user",
    "get_current_admin",
    "require_permission",
    "authenticate_ws_admin",
    "verify_firebase_id_token",
    "set_test_token_verifier",
    "get_firebase_app",
    "IdentityType",
    "Role",
    "AuthScheme",
    "Permission",
    "ROLE_PERMISSIONS",
    "EndpointPolicy",
    "ENDPOINT_POLICIES",
    "has_permission",
    "get_endpoint_policy",
    "is_public_endpoint",
    "AuthenticatedDevice",
    "get_current_device",
    "get_current_actor",
    "resolve_user_voice_identity",
    "check_verification_authorization",
    "set_test_device_registry",
    "get_nonce_store",
    "InMemoryNonceStore",
    "RequestSizeLimiterMiddleware",
    "PayloadTooLargeError",
    "InMemoryRateLimiter",
    "enforce_rate_limit",
    "get_actor_rate_key",
    "acquire_inference_slot",
    "release_inference_slot",
    "load_allowed_cors_origins",
    "load_device_registry",
]

if __name__ == "__main__":
    uvicorn.run("cloud_api:app", host="0.0.0.0", port=8000, reload=False)
