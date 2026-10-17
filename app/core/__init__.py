"""Core configuration, authentication, and error utilities."""
from app.core.config import (
    SERVER_THRESHOLD,
    MAX_AUDIO_SIZE_BYTES,
    ALLOWED_EXTENSIONS,
    DEFAULT_CHALLENGE_TTL_SECONDS,
    DEFAULT_CHALLENGE_LENGTH,
    load_server_threshold,
    load_max_audio_size,
    VOICELOCK_ENV,
    FIREBASE_CREDENTIALS_PATH,
    FIREBASE_PROJECT_ID,
    ADMIN_EMAILS,
    ADMIN_UIDS,
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

