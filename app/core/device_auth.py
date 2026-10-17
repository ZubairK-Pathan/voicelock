"""
app/core/device_auth.py — Hardware terminal (IoT) authentication, replay defense, and actor resolution.

Threat Model & Security Design:
1. Physical Access Points: IoT terminals (e.g. ESP32 door controllers) initiate biometric
   verification on behalf of users standing at the physical portal.
2. Dual Authentication Schemes Supported:
   a. Replay-Resistant HMAC-SHA256 (Recommended):
      - Header: X-Device-ID
      - Header: X-Device-Timestamp (checked against 300s clock skew window)
      - Header: X-Device-Nonce (checked against thread-safe sliding window NonceStore)
      - Header: X-Device-Signature (HMAC-SHA256 over method, path, timestamp, nonce, body hash)
   b. Pre-Shared Secret Key (X-Device-Key):
      - Allowed over HTTPS for constrained devices.
      - Documented Limitation: Static keys over HTTPS lack application-layer replay resistance.
3. Separation of Privileges:
   - Authenticated devices are assigned Role.DEVICE and NEVER granted Role.ADMIN.
   - Devices cannot enumerate users, enroll speakers, delete speakers, or invoke unconstrained /identify.
4. Production Hardening:
   - In production, plain HTTP device requests are rejected (HTTPS mandatory).
   - Missing or empty device registry fails closed.
   - Device credentials in query parameters are strictly rejected.
"""

import hashlib
import hmac
import logging
import os
import threading
import time
from typing import Optional, Union, Dict, Tuple
from pydantic import BaseModel, Field
from fastapi import HTTPException, Request, Depends
from sqlalchemy.orm import Session

from app.core.config import (
    VOICELOCK_ENV,
    MAX_TIMESTAMP_DRIFT_SECONDS,
    load_device_registry,
    load_device_key_fallback_enabled,
)
from app.core.auth_policy import Role
from app.core.auth import AuthenticatedUser, get_current_user
from app.db.session import get_db_context
from app.repositories.user_speaker_repository import UserSpeakerRepository

logger = logging.getLogger(__name__)



# ─── Authenticated Device Domain Model ────────────────────────────────────────

class AuthenticatedDevice(BaseModel):
    """Authenticated physical door controller or access terminal identity."""
    device_id: str = Field(..., description="Unique hardware terminal identifier")
    name: Optional[str] = Field(None, description="Physical location or friendly name")
    role: Role = Field(default=Role.DEVICE, description="Authorization role (strictly Role.DEVICE)")
    auth_scheme: str = Field(..., description="Authentication scheme used ('hmac_sha256' or 'device_key')")

    @property
    def is_admin(self) -> bool:
        return False


# ─── Replay Defense Nonce Store ───────────────────────────────────────────────

class InMemoryNonceStore:
    """
    Thread-safe, memory-bounded store tracking used nonces within the timestamp tolerance window.
    Prevents replay attacks against the HMAC request scheme.
    """
    def __init__(self, ttl_seconds: float = MAX_TIMESTAMP_DRIFT_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        # Mapping: (device_id, nonce) -> expiry_timestamp
        self._nonces: Dict[Tuple[str, str], float] = {}

    def validate_and_record(self, device_id: str, nonce: str, now: Optional[float] = None) -> bool:
        """
        Check if nonce has been used by this device within the TTL window.
        Returns True if nonce is fresh and recorded successfully, False if replayed.
        """
        current_time = time.time() if now is None else now
        with self._lock:
            # Prune expired nonces
            self._prune(current_time)

            key = (device_id, nonce)
            if key in self._nonces:
                return False  # Replay detected!

            self._nonces[key] = current_time + self.ttl_seconds
            return True

    def _prune(self, current_time: float) -> None:
        expired = [k for k, exp in self._nonces.items() if exp <= current_time]
        for k in expired:
            del self._nonces[k]

    def reset_for_testing(self) -> None:
        with self._lock:
            self._nonces.clear()


_default_nonce_store = InMemoryNonceStore()
_test_device_registry: Optional[dict] = None


def get_nonce_store() -> InMemoryNonceStore:
    return _default_nonce_store


def set_test_device_registry(registry: Optional[dict]) -> None:
    """Inject a deterministic device registry for unit tests. Prohibited in production."""
    global _test_device_registry
    current_env = os.getenv("VOICELOCK_ENV", VOICELOCK_ENV).strip().lower()
    if current_env == "production" and registry is not None:
        raise RuntimeError("Test device registries are strictly prohibited in production environment.")
    _test_device_registry = registry


def get_device_registry() -> dict:
    """Return device registry from test injection or environment configuration."""
    if _test_device_registry is not None:
        return _test_device_registry
    return load_device_registry()


# ─── Device Authentication Dependency ─────────────────────────────────────────

async def get_current_device(request: Request) -> AuthenticatedDevice:
    """
    FastAPI dependency: Authenticate IoT device via HTTP headers.
    Supports either HMAC-SHA256 signature scheme or pre-shared X-Device-Key.
    Rejects query parameters, non-HTTPS in production, and stale/replayed requests.
    """
    # 1. Reject credentials in query parameters
    if "device_key" in request.query_params or "device_secret" in request.query_params:
        raise HTTPException(
            status_code=400,
            detail="Device credentials must never be passed in query parameters.",
        )

    # 2. Enforce HTTPS in production
    current_env = os.getenv("VOICELOCK_ENV", VOICELOCK_ENV).strip().lower()
    if current_env == "production":
        is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        if not is_https:
            raise HTTPException(
                status_code=403,
                detail="HTTPS is strictly required for IoT device authentication.",
            )

    # 3. Prevent HTTP header ambiguity / smuggling via duplicate device headers
    for hdr in ("X-Device-ID", "X-Device-Signature", "X-Device-Key", "X-Device-Timestamp", "X-Device-Nonce"):
        if len(request.headers.getlist(hdr)) > 1:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate '{hdr}' headers are strictly prohibited.",
            )

    # 4. Read Device ID
    device_id = request.headers.get("X-Device-ID")
    if not device_id or not device_id.strip():
        raise HTTPException(
            status_code=401,
            detail="Missing required 'X-Device-ID' header.",
        )
    device_id = device_id.strip()

    # 5. Lookup device in registry (Fail closed if registry empty or missing)
    registry = get_device_registry()
    if not registry:
        raise HTTPException(
            status_code=500,
            detail="Device authentication provider is not configured on the server.",
        )

    device_entry = registry.get(device_id)
    if not device_entry:
        # Constant-time dummy hash to resist timing attacks on device enumeration
        dummy_secret = "0" * 32
        hmac.compare_digest(dummy_secret, dummy_secret)
        raise HTTPException(
            status_code=401,
            detail="Invalid device credentials or unknown device identifier.",
        )

    device_secret = str(device_entry.get("secret", ""))
    device_name = device_entry.get("name", device_id)

    # 6. Check Scheme A: Replay-Resistant HMAC-SHA256
    sig_header = request.headers.get("X-Device-Signature")
    if sig_header:
        ts_header = request.headers.get("X-Device-Timestamp")
        nonce_header = request.headers.get("X-Device-Nonce")

        if not ts_header or not nonce_header:
            raise HTTPException(
                status_code=400,
                detail="HMAC authentication requires 'X-Device-Timestamp' and 'X-Device-Nonce' headers.",
            )

        # Validate timestamp within tolerance window
        try:
            req_ts = float(ts_header.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid X-Device-Timestamp format.")

        now = time.time()
        if abs(now - req_ts) > MAX_TIMESTAMP_DRIFT_SECONDS:
            raise HTTPException(
                status_code=401,
                detail="Request timestamp outside acceptable tolerance window (clock skew / stale request).",
            )

        # Validate nonce formatting
        clean_nonce = nonce_header.strip()
        if len(clean_nonce) < 8:
            raise HTTPException(status_code=400, detail="X-Device-Nonce must be at least 8 characters.")

        # Read raw request body hash
        raw_body = await request.body()
        body_digest = hashlib.sha256(raw_body).hexdigest()

        # Build canonical signing string
        method = request.method.upper()
        path = request.url.path
        canonical_string = f"{method}\n{path}\n{ts_header.strip()}\n{clean_nonce}\n{body_digest}"

        expected_sig = hmac.new(
            device_secret.encode("utf-8"),
            canonical_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # Constant-time signature verification MUST precede nonce recording.
        # This prevents unauthenticated attackers from prematurely burning legitimate nonces.
        if not hmac.compare_digest(sig_header.strip(), expected_sig):
            raise HTTPException(status_code=401, detail="Invalid HMAC device signature.")

        # Atomic nonce registration: only executed after proving possession of secret key
        nonce_store = get_nonce_store()
        if not nonce_store.validate_and_record(device_id, clean_nonce, now=now):
            raise HTTPException(
                status_code=401,
                detail="Replay attack detected: X-Device-Nonce has already been consumed.",
            )

        return AuthenticatedDevice(
            device_id=device_id,
            name=device_name,
            role=Role.DEVICE,
            auth_scheme="hmac_sha256",
        )

    # 7. Check Scheme B: Pre-Shared Key (X-Device-Key)
    key_header = request.headers.get("X-Device-Key")
    if key_header:
        if not load_device_key_fallback_enabled():
            raise HTTPException(
                status_code=403,
                detail="Static X-Device-Key authentication is disabled in this environment. Replay-resistant HMAC authentication is required.",
            )

        if not hmac.compare_digest(key_header.strip(), device_secret):
            raise HTTPException(status_code=401, detail="Invalid device key.")

        return AuthenticatedDevice(
            device_id=device_id,
            name=device_name,
            role=Role.DEVICE,
            auth_scheme="device_key",
        )

    raise HTTPException(
        status_code=401,
        detail="Missing device authentication. Provide either 'X-Device-Signature' (HMAC) or 'X-Device-Key'.",
    )


# ─── Unified Actor Dependency & Verification Permission Enforcement ───────────

async def get_current_actor(request: Request) -> Union[AuthenticatedUser, AuthenticatedDevice]:
    """
    Unified dependency for dual-credential endpoints (POST /challenge and POST /verify).
    Accepts either:
    1. Authenticated Web User via Authorization: Bearer <token>
    2. Authenticated IoT Hardware Terminal via X-Device-* headers
    Rejects unauthenticated callers with HTTP 401.
    """
    if "device_key" in request.query_params or "device_secret" in request.query_params:
        raise HTTPException(
            status_code=400,
            detail="Device credentials must never be passed in query parameters.",
        )

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.strip().lower().startswith("bearer "):
        return await get_current_user(request)

    if request.headers.get("X-Device-ID"):
        return await get_current_device(request)

    raise HTTPException(
        status_code=401,
        detail="Missing authentication credentials. Expected Bearer token or Device headers.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def resolve_user_voice_identity(
    user: AuthenticatedUser,
    session: Optional[Session] = None,
) -> Optional[str]:
    """
    Resolve the permitted biometric speaker_id for an authenticated user from the database.
    Queries the persistent UserSpeakerMapping table using the user's verified Firebase UID.
    Never trusts client-supplied claims, email heuristics, or fallback tricks.
    Fails closed on database lookup errors.
    """
    if not user or not user.uid:
        return None

    clean_uid = user.uid.strip()

    def _query(s: Session) -> Optional[str]:
        repo = UserSpeakerRepository(s)
        return repo.get_speaker_id_for_user(clean_uid)

    try:
        if session is not None:
            return _query(session)
        else:
            with get_db_context() as db:
                return _query(db)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Database lookup error during user voice identity resolution: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Database authorization service unavailable.",
        ) from exc


def check_verification_authorization(
    actor: Union[AuthenticatedUser, AuthenticatedDevice],
    claimed_identity: str,
    session: Optional[Session] = None,
) -> None:
    """
    Enforce persistent verification authorization:
    - Admin: Authorized to challenge/verify any registered identity (preserve explicit admin policy).
    - Device: Authorized to initiate verification for any registered speaker at this physical portal.
    - Ordinary User: Authorized ONLY if mapped in UserSpeakerMapping to the claimed speaker identity!
      - If unmapped: Denied (HTTP 403 Forbidden).
      - If mapped to a different speaker: Denied (HTTP 403 Forbidden).
      - On database lookup error: Fails closed (HTTP 500).
    """
    clean_claimed = claimed_identity.strip()
    if not clean_claimed:
        raise HTTPException(status_code=400, detail="Claimed identity must be a non-empty string.")

    if actor.is_admin:
        return

    if isinstance(actor, AuthenticatedDevice):
        # A registered hardware door terminal is authorized to verify enrolled speakers
        return

    if isinstance(actor, AuthenticatedUser):
        mapped_speaker = resolve_user_voice_identity(actor, session=session)
        if not mapped_speaker:
            raise HTTPException(
                status_code=403,
                detail="Forbidden: User account is not mapped to an enrolled speaker identity.",
            )
        if mapped_speaker.lower() != clean_claimed.lower():
            raise HTTPException(
                status_code=403,
                detail=f"Forbidden: You are only authorized to verify your own voice identity ('{mapped_speaker}'). Ordinary users cannot verify arbitrary identities ('{clean_claimed}').",
            )
        return

    raise HTTPException(status_code=403, detail="Forbidden: Unrecognized principal type.")

