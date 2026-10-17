"""
app/core/auth.py — Server-side Firebase ID-token verification, trusted role resolution, and RBAC enforcement.
"""

import asyncio
import os
from typing import Any, Callable, List, Optional, Set
from pathlib import Path

from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

import firebase_admin
from firebase_admin import auth as fb_auth, credentials as fb_credentials

from app.core.config import (
    BASE_DIR,
    FIREBASE_CREDENTIALS_PATH,
    FIREBASE_PROJECT_ID,
    VOICELOCK_ENV,
    load_admin_emails,
    load_admin_uids,
    TRUST_TOKEN_ADMIN_CLAIMS,
)
from app.core.auth_policy import Role, Permission, has_permission

# ─── Authenticated User Domain Model ─────────────────────────────────────────

class AuthenticatedUser(BaseModel):
    """Authenticated human operator or employee identity."""
    uid: str = Field(..., description="Firebase Auth unique user identifier")
    email: Optional[str] = Field(None, description="User email address")
    email_verified: bool = Field(False, description="Whether user email is verified")
    roles: List[Role] = Field(default_factory=lambda: [Role.USER], description="Assigned authorization roles")
    auth_time: Optional[int] = Field(None, description="Unix timestamp of authentication")
    voice_identity: Optional[str] = Field(None, description="Enrolled speaker profile name bound to this user")

    @property
    def is_admin(self) -> bool:
        return Role.ADMIN in self.roles


# ─── Firebase Admin SDK Lifecycle ─────────────────────────────────────────────

_firebase_app: Optional[firebase_admin.App] = None
_firebase_initialized: bool = False
_test_token_verifier: Optional[Callable[[str, bool], dict]] = None


def get_firebase_app() -> Optional[firebase_admin.App]:
    """
    Return the initialized Firebase Admin App singleton.
    Initializes the app exactly once.
    Fails safely in production if credentials cannot be resolved.
    """
    global _firebase_app, _firebase_initialized
    if _firebase_initialized:
        return _firebase_app

    # Check if default app already exists in firebase_admin._apps
    if firebase_admin._apps:
        _firebase_app = firebase_admin.get_app()
        _firebase_initialized = True
        return _firebase_app

    current_env = os.getenv("VOICELOCK_ENV", VOICELOCK_ENV).strip().lower()

    # Determine credential source
    cred = None
    cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH", FIREBASE_CREDENTIALS_PATH)
    if cred_path and os.path.exists(cred_path):
        cred = fb_credentials.Certificate(cred_path)
    elif current_env != "production":
        # Check local development fallback only outside production
        default_dev_path = BASE_DIR / "firebase-credentials.json"
        if default_dev_path.exists():
            cred = fb_credentials.Certificate(str(default_dev_path))

    if cred is not None:
        options = {}
        project_id = os.getenv("FIREBASE_PROJECT_ID", FIREBASE_PROJECT_ID)
        if project_id:
            options["projectId"] = project_id
        _firebase_app = firebase_admin.initialize_app(cred, options)
        _firebase_initialized = True
        return _firebase_app

    if current_env == "production":
        # In production, attempt Application Default Credentials (ADC)
        try:
            cred = fb_credentials.ApplicationDefault()
            options = {}
            project_id = os.getenv("FIREBASE_PROJECT_ID", FIREBASE_PROJECT_ID)
            if project_id:
                options["projectId"] = project_id
            _firebase_app = firebase_admin.initialize_app(cred, options)
            _firebase_initialized = True
            return _firebase_app
        except Exception as exc:
            raise RuntimeError(
                "Production authentication failure: Firebase credentials not configured or resolved."
            ) from exc

    # In development or testing without credentials on disk, do not crash application import.
    _firebase_initialized = True
    return None


def reset_firebase_app_for_testing() -> None:
    """Helper to reset initialization state during tests."""
    global _firebase_app, _firebase_initialized
    _firebase_app = None
    _firebase_initialized = False


def set_test_token_verifier(verifier: Optional[Callable[[str, bool], dict]]) -> None:
    """
    Inject a custom token verifier callable for deterministic unit tests.
    Strictly prohibited in production environments.
    """
    global _test_token_verifier
    current_env = os.getenv("VOICELOCK_ENV", VOICELOCK_ENV).strip().lower()
    if current_env == "production" and verifier is not None:
        raise RuntimeError("Test token verifiers are strictly prohibited in production environment.")
    _test_token_verifier = verifier


def get_test_token_verifier() -> Optional[Callable[[str, bool], dict]]:
    return _test_token_verifier


# ─── Token Verification & Role Resolution ─────────────────────────────────────

def extract_bearer_token(auth_header: Optional[str]) -> str:
    """
    Extract and validate Bearer token format from HTTP Authorization header.
    Rejects missing or malformed headers with HTTP 401.
    """
    if not auth_header or not auth_header.strip():
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = auth_header.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization scheme. Expected 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        )

    return parts[1].strip()


def resolve_user_roles(claims: dict) -> List[Role]:
    """
    Resolve user roles strictly from trusted server-side sources:
    1. Verified token custom claims (`admin` boolean or `role`/`roles` claim).
    2. Server-side configured ADMIN_EMAILS or ADMIN_UIDS.
    Client-supplied request parameters or form fields are NEVER trusted.
    """
    roles = [Role.USER]
    is_admin = False

    # Check verified token custom claims (guarded by TRUST_TOKEN_ADMIN_CLAIMS)
    env = os.getenv("VOICELOCK_ENV", VOICELOCK_ENV).strip().lower()
    trust_claims = os.getenv(
        "TRUST_TOKEN_ADMIN_CLAIMS",
        "true" if env != "production" else "false"
    ).lower() in ("true", "1")
    if trust_claims:
        if claims.get("admin") is True:
            is_admin = True
        elif claims.get("role") == "admin":
            is_admin = True
        elif isinstance(claims.get("roles"), list) and "admin" in claims.get("roles", []):
            is_admin = True

    # Check server-side configured admin bootstrap lists
    email = claims.get("email")
    if email and email.strip().lower() in load_admin_emails():
        is_admin = True

    uid = claims.get("uid") or claims.get("sub")
    if uid and uid.strip() in load_admin_uids():
        is_admin = True

    if is_admin and Role.ADMIN not in roles:
        roles.insert(0, Role.ADMIN)

    return roles


def verify_firebase_id_token(token: str, check_revoked: bool = False) -> dict:
    """
    Verify a Firebase ID token.
    Uses injected test verifier if active (outside production), otherwise uses Firebase Admin SDK.
    Enforces check_revoked for sensitive administrative operations.
    """
    try:
        if _test_token_verifier is not None:
            current_env = os.getenv("VOICELOCK_ENV", VOICELOCK_ENV).strip().lower()
            if current_env == "production":
                raise RuntimeError("Test token verifier cannot be executed in production.")
            return _test_token_verifier(token, check_revoked)

        fb_app = get_firebase_app()
        if fb_app is None:
            raise HTTPException(
                status_code=500,
                detail="Authentication provider is not configured on the server.",
            )

        decoded_claims = fb_auth.verify_id_token(token, app=fb_app, check_revoked=check_revoked)
        return decoded_claims
    except HTTPException:
        raise
    except RuntimeError:
        raise
    except fb_auth.RevokedIdTokenError:
        raise HTTPException(
            status_code=401,
            detail="Authentication token has been revoked.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\", error_description=\"Token has been revoked\""},
        )
    except fb_auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=401,
            detail="Authentication token has expired.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\", error_description=\"Token has expired\""},
        )
    except (fb_auth.InvalidIdTokenError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        )
    except fb_auth.CertificateFetchError:
        raise HTTPException(
            status_code=503,
            detail="Authentication verification service is temporarily unavailable.",
        )
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Authentication verification failed.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        )


# ─── FastAPI Request Dependencies ────────────────────────────────────────────

async def get_current_user(request: Request) -> AuthenticatedUser:
    """
    Dependency: Authenticate web user from Authorization header.
    Validates token signature and expiration (check_revoked=False).
    """
    auth_header = request.headers.get("Authorization")
    token = extract_bearer_token(auth_header)
    claims = verify_firebase_id_token(token, check_revoked=False)

    uid = claims.get("uid") or claims.get("sub")
    if not uid:
        raise HTTPException(status_code=401, detail="Token missing subject identifier.")

    roles = resolve_user_roles(claims)
    return AuthenticatedUser(
        uid=uid,
        email=claims.get("email"),
        email_verified=bool(claims.get("email_verified", False)),
        roles=roles,
        auth_time=claims.get("auth_time"),
        voice_identity=claims.get("voice_identity") or claims.get("speaker_name"),
    )


async def get_current_admin(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """
    Dependency: Authenticate administrator.
    Re-verifies token with check_revoked=True to enforce revocation on admin operations,
    and ensures Role.ADMIN is granted.
    """
    # Re-verify with check_revoked=True
    auth_header = request.headers.get("Authorization")
    token = extract_bearer_token(auth_header)
    verify_firebase_id_token(token, check_revoked=True)

    if not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Administrative privileges required.",
        )
    return user


def require_permission(permission: Permission):
    """
    Dependency factory: verify that the authenticated user possesses the required permission.
    """
    async def permission_checker(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        has_perm = any(has_permission(role, permission) for role in user.roles)
        if not has_perm:
            raise HTTPException(
                status_code=403,
                detail=f"Forbidden: Missing required permission '{permission.value}'.",
            )
        return user
    return permission_checker


# ─── WebSocket Authentication Helper ─────────────────────────────────────────

async def authenticate_ws_admin(websocket: WebSocket, timeout: float = 5.0) -> AuthenticatedUser:
    """
    Authenticate WebSocket connection for administrative operations.
    Protocol:
    1. Server accepts connection.
    2. Client must send initial JSON frame within `timeout` seconds:
       `{"type": "auth", "token": "<bearer_token>"}`
    3. Server verifies token with revocation check and validates Role.ADMIN.
    4. On failure: server sends error message and closes with code 1008 (Policy Violation).
    5. On success: server sends `{"type": "auth_ok", "uid": ..., "roles": [...]}` and returns AuthenticatedUser.
    """
    try:
        msg = await asyncio.wait_for(websocket.receive_json(), timeout=timeout)
    except (asyncio.TimeoutError, Exception):
        await websocket.close(code=1008, reason="Authentication timeout or invalid initial message")
        raise WebSocketDisconnect(code=1008)

    if not isinstance(msg, dict) or msg.get("type") != "auth" or not msg.get("token"):
        await websocket.send_json({"error": "Authentication failed", "detail": "Expected {'type': 'auth', 'token': '...'}"})
        await websocket.close(code=1008, reason="Missing or invalid authentication frame")
        raise WebSocketDisconnect(code=1008)

    token = str(msg["token"]).strip()
    try:
        claims = verify_firebase_id_token(token, check_revoked=True)
        roles = resolve_user_roles(claims)
        uid = claims.get("uid") or claims.get("sub")
        if not uid or Role.ADMIN not in roles:
            await websocket.send_json({"error": "Forbidden", "detail": "Administrative privileges required"})
            await websocket.close(code=1008, reason="Administrative privileges required")
            raise WebSocketDisconnect(code=1008)

        user = AuthenticatedUser(
            uid=uid,
            email=claims.get("email"),
            email_verified=bool(claims.get("email_verified", False)),
            roles=roles,
            auth_time=claims.get("auth_time"),
        )
        await websocket.send_json({
            "type": "auth_ok",
            "uid": user.uid,
            "roles": [r.value for r in user.roles],
        })
        return user
    except WebSocketDisconnect:
        raise
    except HTTPException as exc:
        await websocket.send_json({"error": "Authentication failed", "detail": exc.detail})
        await websocket.close(code=1008, reason=exc.detail)
        raise WebSocketDisconnect(code=1008)
    except Exception:
        await websocket.send_json({"error": "Authentication failed", "detail": "Token validation error"})
        await websocket.close(code=1008, reason="Authentication failed")
        raise WebSocketDisconnect(code=1008)
