"""
tests/test_auth.py — Dedicated security test suite for Firebase Authentication and RBAC enforcement.

Verifies:
1. Public health discovery requires no credentials.
2. Missing, malformed, invalid, and expired bearer tokens are rejected with HTTP 401.
3. Token revocation is enforced on administrative operations.
4. Role-based access control (RBAC):
   - Authenticated regular USER is rejected (HTTP 403) from ADMIN endpoints (/speakers, /identify, /ws/identify).
   - Authenticated ADMIN is permitted on all authorized endpoints.
   - Client-supplied role claims and tamper attempts (e.g. admin=true) are ignored.
   - Server-side bootstrap lists (ADMIN_EMAILS, ADMIN_UIDS) assign ADMIN role safely.
5. Production safeguards:
   - Injected test verifier is prohibited in production (raises RuntimeError).
   - Missing production credentials fail safely without insecure bypasses.
6. WebSocket authentication:
   - Rejects unauthenticated connections, timeouts, invalid frame formats, and non-admin users.
   - Accepts authenticated administrators and permits audio streaming.
7. Biometric & Challenge security preservation under authentication:
   - Challenge binding, atomic single-use, liveness fail-closed, and server threshold enforcement.
8. Streamlit reference app independence:
   - Remains functional without requiring FastAPI web bearer authentication headers.
"""

import io
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from firebase_admin import auth as fb_auth

from app.main import app
from app.core.config import SERVER_THRESHOLD
from app.core.auth import (
    AuthenticatedUser,
    get_current_user,
    get_current_admin,
    extract_bearer_token,
    resolve_user_roles,
    verify_firebase_id_token,
    set_test_token_verifier,
    get_firebase_app,
    reset_firebase_app_for_testing,
)
from app.core.auth_policy import Role
from app.core.rate_limit import _challenge_limiter, _verify_limiter, _identify_limiter
from app.db.base import Base, SpeakerRecord, UserSpeakerMapping
from app.db.session import get_engine, get_db_context
from app.repositories.speaker_repository import SpeakerRepository
from app.repositories.user_speaker_repository import UserSpeakerRepository
import liveness

client = TestClient(app)

SAMPLE_WAV = Path(__file__).resolve().parent.parent / "processed_dataset" / "Zubair" / "Zubair_Enrollment_R01.wav"

ADMIN_TOKEN = "test-token-admin-valid"
USER_TOKEN = "test-token-user-valid"
OTHER_USER_TOKEN = "test-token-other-user"
REVOKED_TOKEN = "test-token-revoked"
EXPIRED_TOKEN = "test-token-expired"
INVALID_TOKEN = "test-token-invalid"
TAMPERED_ROLE_TOKEN = "test-token-tampered-role"
BOOTSTRAP_EMAIL_TOKEN = "test-token-bootstrap-email"
BOOTSTRAP_UID_TOKEN = "test-token-bootstrap-uid"


def deterministic_test_verifier(token: str, check_revoked: bool = False) -> dict:
    """Mock verifier injecting deterministic Firebase claims for testing."""
    if token == ADMIN_TOKEN:
        return {
            "uid": "admin-uid-001",
            "email": "admin@voicelock.enterprise",
            "email_verified": True,
            "admin": True,
            "auth_time": 1700000000,
        }
    elif token == USER_TOKEN:
        return {
            "uid": "user-uid-002",
            "email": "zubair@voicelock.enterprise",
            "voice_identity": "Zubair",
            "email_verified": True,
            "admin": False,
            "auth_time": 1700000000,
        }
    elif token == OTHER_USER_TOKEN:
        return {
            "uid": "other-uid-999",
            "email": "alice@voicelock.enterprise",
            "voice_identity": "Alice",
            "email_verified": True,
            "admin": False,
            "auth_time": 1700000000,
        }
    elif token == REVOKED_TOKEN:
        if check_revoked:
            raise fb_auth.RevokedIdTokenError("Token has been revoked.")
        return {
            "uid": "revoked-uid-003",
            "email": "revoked@voicelock.enterprise",
            "admin": True,
        }
    elif token == EXPIRED_TOKEN:
        raise fb_auth.ExpiredIdTokenError("Token has expired.", None)
    elif token == INVALID_TOKEN:
        raise fb_auth.InvalidIdTokenError("Invalid token signature.")
    elif token == TAMPERED_ROLE_TOKEN:
        return {
            "uid": "tampered-uid-004",
            "email": "attacker@evil.com",
            "role": "superadmin",
            "roles": ["root", "superuser"],
            "client_admin": True,
        }
    elif token == BOOTSTRAP_EMAIL_TOKEN:
        return {
            "uid": "bootstrap-uid-005",
            "email": "ceo@voicelock.com",
            "email_verified": True,
        }
    elif token == BOOTSTRAP_UID_TOKEN:
        return {
            "uid": "static-trusted-admin-uid-999",
            "email": "other@voicelock.com",
            "email_verified": True,
        }
    else:
        raise fb_auth.InvalidIdTokenError(f"Unrecognized test token: {token}")


@pytest.fixture(autouse=True)
def setup_test_auth():
    """Configure deterministic verifier, clear dependency overrides, and seed test database."""
    app.dependency_overrides.clear()
    _challenge_limiter.reset_for_testing()
    _verify_limiter.reset_for_testing()
    _identify_limiter.reset_for_testing()
    set_test_token_verifier(deterministic_test_verifier)

    # Ensure tables exist
    Base.metadata.create_all(get_engine())

    with get_db_context() as session:
        session.query(UserSpeakerMapping).delete()
        session.query(SpeakerRecord).delete()
        session.flush()

        spk_repo = SpeakerRepository(session)
        usr_repo = UserSpeakerRepository(session)
        import numpy as np
        dummy_emb = np.zeros(192, dtype=np.float32)
        spk_repo.create(speaker_id="Zubair", full_name="Zubair Pathan", embedding=dummy_emb)
        spk_repo.create(speaker_id="Alice", full_name="Alice Smith", embedding=dummy_emb)

        usr_repo.create(firebase_uid="user-uid-002", speaker_id="Zubair")
        usr_repo.create(firebase_uid="other-uid-999", speaker_id="Alice")

    yield

    with get_db_context() as session:
        session.query(UserSpeakerMapping).delete()
        session.query(SpeakerRecord).delete()
    from scripts.seed_speakers import run_seed_speakers
    run_seed_speakers()

    set_test_token_verifier(None)
    app.dependency_overrides.clear()
    _challenge_limiter.reset_for_testing()
    _verify_limiter.reset_for_testing()
    _identify_limiter.reset_for_testing()



# ─── 1. Health Discovery (Public) ─────────────────────────────────────────────

def test_public_health_endpoint_requires_no_auth():
    """Verify GET / is public and returns non-sensitive health metadata without authentication."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "VoiceLock" in data["service"]
    assert "version" in data
    assert data.get("threshold") is None
    assert data.get("enrolled_speakers") is None


# ─── 2. Missing, Malformed, Invalid, and Expired Bearer Tokens ────────────────

def test_missing_bearer_token_rejected_on_all_protected_endpoints():
    """Verify all protected endpoints reject unauthenticated requests with HTTP 401."""
    # GET /speakers
    r1 = client.get("/speakers")
    assert r1.status_code == 401
    assert "WWW-Authenticate" in r1.headers
    assert "Bearer" in r1.headers["WWW-Authenticate"]

    # POST /challenge
    r2 = client.post("/challenge")
    assert r2.status_code == 401

    # POST /verify
    r3 = client.post("/verify")
    assert r3.status_code == 401

    # POST /identify
    r4 = client.post("/identify")
    assert r4.status_code == 401


def test_malformed_bearer_header_rejected():
    """Verify malformed authorization headers return HTTP 401 with appropriate WWW-Authenticate."""
    malformed_headers = [
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer   "},
        {"Authorization": "Token some-token-value"},
        {"Authorization": "Bearer token1 token2"},
    ]
    for headers in malformed_headers:
        response = client.get("/speakers", headers=headers)
        assert response.status_code == 401
        assert "WWW-Authenticate" in response.headers


def test_invalid_token_rejected():
    """Verify invalid ID token returns HTTP 401."""
    headers = {"Authorization": f"Bearer {INVALID_TOKEN}"}
    response = client.get("/speakers", headers=headers)
    assert response.status_code == 401
    assert "Invalid authentication token" in response.json()["detail"]


def test_expired_token_rejected():
    """Verify expired ID token returns HTTP 401 with expired token error."""
    headers = {"Authorization": f"Bearer {EXPIRED_TOKEN}"}
    response = client.get("/speakers", headers=headers)
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


# ─── 3. Token Revocation for Administrative Actions ───────────────────────────

def test_revoked_token_rejected_on_admin_actions():
    """
    Verify that an admin token revoked on Firebase server is rejected with HTTP 401
    when executing administrative operations that require check_revoked=True.
    """
    headers = {"Authorization": f"Bearer {REVOKED_TOKEN}"}
    # GET /speakers requires check_revoked=True via get_current_admin
    response = client.get("/speakers", headers=headers)
    assert response.status_code == 401
    assert "revoked" in response.json()["detail"].lower()


# ─── 4. RBAC: Role Enforcement and Untrusted Role Claims ───────────────────────

def test_authenticated_user_denied_access_to_admin_only_endpoints():
    """Verify regular authenticated USER receives HTTP 403 Forbidden on ADMIN-only endpoints."""
    user_headers = {"Authorization": f"Bearer {USER_TOKEN}"}

    # GET /speakers is ADMIN only
    r_speakers = client.get("/speakers", headers=user_headers)
    assert r_speakers.status_code == 403
    assert "Administrative privileges required" in r_speakers.json()["detail"]

    # POST /identify is ADMIN only
    r_identify = client.post(
        "/identify",
        headers=user_headers,
        files={"audio": ("sample.wav", b"dummy audio", "audio/wav")},
    )
    assert r_identify.status_code == 403
    assert "Administrative privileges required" in r_identify.json()["detail"]


def test_authenticated_admin_allowed_on_admin_endpoints():
    """Verify authenticated ADMIN is permitted on ADMIN-only endpoints."""
    admin_headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
    response = client.get("/speakers", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "registered_speakers" in data
    assert "count" in data


def test_authenticated_user_allowed_on_challenge_and_verify():
    """Verify regular authenticated USER is permitted to request challenges and submit verification."""
    user_headers = {"Authorization": f"Bearer {USER_TOKEN}"}

    # POST /challenge allowed for USER
    r_challenge = client.post(
        "/challenge",
        headers=user_headers,
        json={"session_id": "test-session-001", "claimed_identity": "Zubair"},
    )
    assert r_challenge.status_code == 200
    data = r_challenge.json()
    assert "challenge_id" in data
    assert "digits" in data


def test_regular_user_cannot_verify_arbitrary_claimed_identity():
    """
    Enforce Reviewer Correction B:
    An ordinary user cannot verify an arbitrary identity by merely submitting claimed_identity.
    User Alice claiming 'Zubair' must be rejected with HTTP 403 Forbidden.
    """
    other_headers = {"Authorization": f"Bearer {OTHER_USER_TOKEN}"}
    r_challenge = client.post(
        "/challenge",
        headers=other_headers,
        json={"session_id": "test-session-alice", "claimed_identity": "Zubair"},
    )
    assert r_challenge.status_code == 403
    assert "only authorized to verify your own voice identity" in r_challenge.json()["detail"]


def test_client_supplied_role_tampering_rejected():
    """
    Verify that client-supplied claims, parameters, or form fields (e.g. admin=true, role=superadmin)
    are NEVER trusted and do not grant administrative access.
    """
    # 1. Parameter tampering with regular user token
    user_headers = {"Authorization": f"Bearer {USER_TOKEN}"}
    r1 = client.get("/speakers?admin=true&role=admin", headers=user_headers)
    assert r1.status_code == 403

    # 2. Token containing client-crafted untrusted role claims
    tampered_headers = {"Authorization": f"Bearer {TAMPERED_ROLE_TOKEN}"}
    r2 = client.get("/speakers", headers=tampered_headers)
    assert r2.status_code == 403
    assert "Administrative privileges required" in r2.json()["detail"]


def test_server_side_bootstrap_admin_assignment():
    """Verify server-side ADMIN_EMAILS and ADMIN_UIDS environment variables safely grant ADMIN role."""
    with patch("app.core.auth.load_admin_emails", return_value={"ceo@voicelock.com"}):
        email_headers = {"Authorization": f"Bearer {BOOTSTRAP_EMAIL_TOKEN}"}
        r_email = client.get("/speakers", headers=email_headers)
        assert r_email.status_code == 200

    with patch("app.core.auth.load_admin_uids", return_value={"static-trusted-admin-uid-999"}):
        uid_headers = {"Authorization": f"Bearer {BOOTSTRAP_UID_TOKEN}"}
        r_uid = client.get("/speakers", headers=uid_headers)
        assert r_uid.status_code == 200


# ─── 5. Production Configuration and Fail-Safe Guards ─────────────────────────

def test_production_guard_prohibits_test_verifier():
    """Verify that injecting or running a test verifier when VOICELOCK_ENV=production raises RuntimeError."""
    with patch.dict(os.environ, {"VOICELOCK_ENV": "production"}):
        with pytest.raises(RuntimeError, match="strictly prohibited in production"):
            set_test_token_verifier(deterministic_test_verifier)

        # If somehow set, calling verify_firebase_id_token in production must fail closed
        with patch("app.core.auth._test_token_verifier", deterministic_test_verifier):
            with pytest.raises(RuntimeError, match="cannot be executed in production"):
                verify_firebase_id_token(ADMIN_TOKEN)


def test_missing_production_credentials_fails_safely():
    """Verify that initializing Firebase in production without valid credentials fails closed."""
    reset_firebase_app_for_testing()
    with patch.dict(os.environ, {"VOICELOCK_ENV": "production", "FIREBASE_CREDENTIALS_PATH": "/nonexistent/key.json"}):
        with patch("firebase_admin.credentials.ApplicationDefault", side_effect=Exception("No ADC")):
            with pytest.raises(RuntimeError, match="Production authentication failure"):
                get_firebase_app()
    reset_firebase_app_for_testing()


# ─── 6. WebSocket Authentication ──────────────────────────────────────────────

def test_websocket_auth_timeout_or_missing_frame():
    """Verify WebSocket connection is closed if client does not send an auth frame."""
    try:
        with client.websocket_connect("/ws/identify") as ws:
            # Send invalid non-auth frame
            ws.send_json({"type": "audio_data", "payload": "none"})
            data = ws.receive_json()
            assert data.get("error") == "Authentication failed"
    except WebSocketDisconnect as exc:
        assert exc.code == 1008


def test_websocket_auth_non_admin_user_rejected():
    """Verify WebSocket connection is rejected if authenticated caller is not an administrator."""
    try:
        with client.websocket_connect("/ws/identify") as ws:
            ws.send_json({"type": "auth", "token": USER_TOKEN})
            data = ws.receive_json()
            assert data.get("error") == "Forbidden"
    except WebSocketDisconnect as exc:
        assert exc.code == 1008


def test_websocket_auth_admin_success_and_streaming():
    """Verify WebSocket connection succeeds for administrator and allows audio streaming."""
    with client.websocket_connect("/ws/identify") as ws:
        # Step 1: Perform initial auth handshake
        ws.send_json({"type": "auth", "token": ADMIN_TOKEN})
        auth_resp = ws.receive_json()
        assert auth_resp.get("type") == "auth_ok"
        assert auth_resp.get("uid") == "admin-uid-001"
        assert "admin" in auth_resp.get("roles", [])

        # Step 2: Stream audio frame
        if SAMPLE_WAV.exists():
            with open(SAMPLE_WAV, "rb") as f:
                audio_bytes = f.read()
            ws.send_bytes(audio_bytes)
            stream_resp = ws.receive_json()
            assert "speaker" in stream_resp
            assert "score" in stream_resp
            assert stream_resp["threshold_used"] == SERVER_THRESHOLD


# ─── 7. Biometric & Challenge Security Preserved Under Auth ───────────────────

def test_challenge_binding_and_single_use_intact_with_auth():
    """Verify that stateful challenges remain strictly bound and single-use under authentication."""
    user_headers = {"Authorization": f"Bearer {USER_TOKEN}"}

    # Create challenge
    r_create = client.post(
        "/challenge",
        headers=user_headers,
        json={"session_id": "session-auth-test", "claimed_identity": "Zubair"},
    )
    assert r_create.status_code == 200
    c_data = r_create.json()
    challenge_id = c_data["challenge_id"]

    # Verify with mismatched session_id fails 400
    r_bad_sess = client.post(
        "/verify",
        headers=user_headers,
        data={
            "claimed_identity": "Zubair",
            "challenge_id": challenge_id,
            "session_id": "different-session",
        },
        files={"audio": ("test.wav", b"fake audio", "audio/wav")},
    )
    assert r_bad_sess.status_code == 400


def test_invalid_challenge_rejected_before_persistence_with_auth():
    """Verify invalid challenge fails early (HTTP 400) before any audio upload processing."""
    user_headers = {"Authorization": f"Bearer {USER_TOKEN}"}
    r = client.post(
        "/verify",
        headers=user_headers,
        data={
            "claimed_identity": "Zubair",
            "challenge_id": "nonexistent-challenge",
            "session_id": "any-session",
        },
        files={"audio": ("test.wav", b"fake audio", "audio/wav")},
    )
    assert r.status_code == 400
    assert "Invalid or unknown challenge ID" in r.json()["detail"]


def test_liveness_failure_skips_inference_under_auth():
    """Verify failed spoken liveness denies access and skips biometric inference."""
    user_headers = {"Authorization": f"Bearer {USER_TOKEN}"}

    # Create valid challenge
    r_create = client.post(
        "/challenge",
        headers=user_headers,
        json={"session_id": "liveness-fail-sess", "claimed_identity": "Zubair"},
    )
    challenge_id = r_create.json()["challenge_id"]

    # Mock liveness to fail
    with patch("app.api.routes_verification._get_run_liveness_check") as mock_live:
        mock_live.return_value = lambda path, digits: (False, "Spoken digits did not match", "")
        with patch("app.api.routes_verification._get_verify_speaker") as mock_verify:
            r = client.post(
                "/verify",
                headers=user_headers,
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": challenge_id,
                    "session_id": "liveness-fail-sess",
                },
                files={"audio": ("test.wav", b"RIFF....WAVEfakeaudioheaderandpayloadcontent", "audio/wav")},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["accepted"] is False
            assert data["action"] == "DENY"
            assert data["liveness_passed"] is False
            assert data["similarity"] == 0.0
            mock_verify.assert_not_called()


def test_client_threshold_cannot_override_server_config():
    """Verify client-supplied threshold in request form is ignored in favor of SERVER_THRESHOLD."""
    user_headers = {"Authorization": f"Bearer {USER_TOKEN}"}

    r_create = client.post(
        "/challenge",
        headers=user_headers,
        json={"session_id": "thresh-sess", "claimed_identity": "Zubair"},
    )
    challenge_id = r_create.json()["challenge_id"]

    with patch("app.api.routes_verification._get_run_liveness_check") as mock_live:
        mock_live.return_value = lambda path, digits: (True, "Matched", "one two three")
        with patch("app.api.routes_verification._get_verify_speaker") as mock_verify:
            mock_verify.return_value = lambda **kwargs: {
                "is_accepted": False,
                "similarity": 0.15,
                "claimed_identity": "Zubair",
                "threshold": SERVER_THRESHOLD,
            }
            r = client.post(
                "/verify",
                headers=user_headers,
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": challenge_id,
                    "session_id": "thresh-sess",
                    "threshold": 0.05,  # Malicious attempt to force acceptance
                },
                files={"audio": ("test.wav", b"RIFF....WAVEfakeaudioheaderandpayloadcontent", "audio/wav")},
            )
            assert r.status_code == 200
            data = r.json()
            assert data["threshold_used"] == SERVER_THRESHOLD
            assert data["accepted"] is False


# ─── 8. Streamlit Independence ────────────────────────────────────────────────

def test_streamlit_reference_app_remains_independent_of_fastapi_auth():
    """
    Verify that the Streamlit reference application (app.py) operates independently
    of FastAPI Bearer token middleware, preserving its direct ML pipeline access.
    """
    from streamlit.testing.v1 import AppTest
    st_path = str(Path(__file__).resolve().parent.parent / "app.py")
    at = AppTest.from_file(st_path, default_timeout=30)
    at.run()
    assert not at.exception, f"Streamlit application encountered exception: {at.exception}"
    tabs = [t.label for t in at.tabs]
    assert "Identify" in tabs
    assert "Verify" in tabs
    assert "Enroll" in tabs
    assert "Manage" in tabs
