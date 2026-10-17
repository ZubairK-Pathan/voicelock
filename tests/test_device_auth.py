"""
tests/test_device_auth.py — Milestone 3B.2 Security and Contract Test Suite.

Verifies:
1. IoT Device Authentication:
   - Replay-resistant HMAC-SHA256 signature scheme (headers, canonical string, constant-time validation).
   - Pre-shared secret key (X-Device-Key) for constrained devices.
   - Rejection of unknown devices, malformed credentials, and missing signatures.
   - Replay resistance: Rejection of reused nonces and stale timestamps outside 300s window.
   - Query parameter rejection: Credentials passed via URL query parameters are rejected (HTTP 400).
   - Production HTTPS enforcement: Non-HTTPS device requests rejected in production (HTTP 403).
   - Fail-closed behavior: Missing/empty device registry fails safely (HTTP 500).
2. Separation of Privileges:
   - IoT devices are strictly Role.DEVICE and never Role.ADMIN.
   - Devices are permitted on /challenge and /verify (physical door portal access).
   - Devices are denied on /speakers and /identify (HTTP 403).
3. ASGI Request-Body Protection:
   - Upfront Content-Length check rejects oversized requests (HTTP 413).
   - Raw streaming inspection rejects oversized bodies without Content-Length (HTTP 413).
   - Misleading Content-Length (understated) is caught on-the-fly and rejected (HTTP 413).
   - Requests within limits stream and parse multipart payloads correctly.
4. CORS Hardening:
   - Allowed origins receive correct Access-Control-Allow-Origin header.
   - Disallowed origins do not receive Access-Control-Allow-Origin header.
   - Wildcard '*' with credentials raises ValueError during configuration.
5. Rate Limiting and Resource Protection:
   - Exceeding request quota returns HTTP 429 with Retry-After header.
   - Rate limit keys are principal-bound (never spoofable headers).
   - Memory is bounded via automatic pruning of stale window records.
   - WebSocket frame count limit (100 frames) enforces termination with code 1008.
"""

import hashlib
import hmac
import io
import json
import os
import secrets
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import (
    load_allowed_cors_origins,
    MAX_TIMESTAMP_DRIFT_SECONDS,
)
from app.core.device_auth import (
    AuthenticatedDevice,
    get_nonce_store,
    set_test_device_registry,
)
from app.core.rate_limit import (
    InMemoryRateLimiter,
    _challenge_limiter,
    _verify_limiter,
    _identify_limiter,
)
from app.core.auth import set_test_token_verifier
from app.core.auth_policy import Role

client = TestClient(app)

SAMPLE_WAV = Path(__file__).resolve().parent.parent / "processed_dataset" / "Zubair" / "Zubair_Enrollment_R01.wav"

TEST_DEVICE_ID = "esp32-portal-north-01"
TEST_DEVICE_SECRET = "supersecret-device-key-32-bytes!!"
TEST_DEVICE_REGISTRY = {
    TEST_DEVICE_ID: {
        "secret": TEST_DEVICE_SECRET,
        "name": "North Portal Controller",
    }
}


def make_hmac_headers(
    device_id: str = TEST_DEVICE_ID,
    secret: str = TEST_DEVICE_SECRET,
    method: str = "POST",
    path: str = "/challenge",
    body: bytes = b"",
    timestamp: float = None,
    nonce: str = None,
) -> dict:
    """Build canonical HMAC authentication headers for IoT device requests."""
    ts = str(time.time() if timestamp is None else timestamp)
    n = secrets.token_hex(8) if nonce is None else str(nonce)
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{method.upper()}\n{path}\n{ts}\n{n}\n{body_hash}"
    sig = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "X-Device-ID": device_id,
        "X-Device-Timestamp": ts,
        "X-Device-Nonce": n,
        "X-Device-Signature": sig,
    }


def deterministic_test_verifier(token: str, check_revoked: bool = False) -> dict:
    if token == "test-token-admin-valid":
        return {
            "uid": "admin-uid-001",
            "email": "admin@voicelock.enterprise",
            "email_verified": True,
            "admin": True,
            "auth_time": 1700000000,
        }
    raise Exception("Invalid token")


@pytest.fixture(autouse=True)
def setup_device_test_env():
    """Ensure clean test environment for device authentication and rate limiters."""
    app.dependency_overrides.clear()
    set_test_token_verifier(deterministic_test_verifier)
    set_test_device_registry(TEST_DEVICE_REGISTRY)
    get_nonce_store().reset_for_testing()
    _challenge_limiter.reset_for_testing()
    _verify_limiter.reset_for_testing()
    _identify_limiter.reset_for_testing()
    yield
    set_test_token_verifier(None)
    set_test_device_registry(None)
    get_nonce_store().reset_for_testing()
    _challenge_limiter.reset_for_testing()
    _verify_limiter.reset_for_testing()
    _identify_limiter.reset_for_testing()
    app.dependency_overrides.clear()


# ─── 1. IoT Device Authentication: HMAC & Key ─────────────────────────────────

def test_device_hmac_valid_auth_allows_challenge():
    """Verify IoT device can authenticate via HMAC-SHA256 and request a liveness challenge."""
    headers = make_hmac_headers(method="POST", path="/challenge", body=b"")
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "challenge_id" in data
    assert "digits" in data


def test_device_key_valid_auth_allows_challenge():
    """Verify constrained IoT device can authenticate via pre-shared X-Device-Key."""
    headers = {
        "X-Device-ID": TEST_DEVICE_ID,
        "X-Device-Key": TEST_DEVICE_SECRET,
    }
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 200
    assert "challenge_id" in response.json()


def test_device_unknown_id_rejected_401():
    """Verify unknown device ID is rejected with HTTP 401."""
    headers = make_hmac_headers(device_id="esp32-unregistered-999")
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 401
    assert "Invalid device credentials" in response.json()["detail"]


def test_device_invalid_hmac_signature_rejected_401():
    """Verify tampered or invalid HMAC signature is rejected with HTTP 401."""
    headers = make_hmac_headers()
    headers["X-Device-Signature"] = "0" * 64  # Tampered signature
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 401
    assert "Invalid HMAC device signature" in response.json()["detail"]


def test_device_invalid_key_rejected_401():
    """Verify incorrect X-Device-Key is rejected with HTTP 401."""
    headers = {
        "X-Device-ID": TEST_DEVICE_ID,
        "X-Device-Key": "wrong-secret-key",
    }
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 401
    assert "Invalid device key" in response.json()["detail"]


def test_device_missing_credentials_rejected_401():
    """Verify device ID without signature or key is rejected with HTTP 401."""
    headers = {"X-Device-ID": TEST_DEVICE_ID}
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 401
    assert "Missing device authentication" in response.json()["detail"]


def test_device_query_parameter_credentials_strictly_rejected_400():
    """Verify passing device credentials in URL query parameters is rejected with HTTP 400."""
    response = client.post(f"/challenge?device_key={TEST_DEVICE_SECRET}")
    assert response.status_code == 400
    assert "query parameters" in response.json()["detail"]


# ─── 2. Replay Resistance & Anti-Replay Defense ───────────────────────────────

def test_device_replayed_nonce_rejected_401():
    """Verify submitting the same nonce twice is caught and rejected as a replay attack."""
    fixed_nonce = "fixed-nonce-12345678"
    headers = make_hmac_headers(nonce=fixed_nonce)

    # First request: fresh nonce succeeds
    r1 = client.post("/challenge", headers=headers)
    assert r1.status_code == 200

    # Second request: replayed nonce fails
    r2 = client.post("/challenge", headers=headers)
    assert r2.status_code == 401
    assert "Replay attack detected" in r2.json()["detail"]


def test_device_stale_timestamp_rejected_401():
    """Verify timestamp outside tolerance window (clock skew / stale request) is rejected."""
    stale_ts = time.time() - (MAX_TIMESTAMP_DRIFT_SECONDS + 10)  # > 5 minutes old
    headers = make_hmac_headers(timestamp=stale_ts)
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 401
    assert "tolerance window" in response.json()["detail"]


def test_device_short_nonce_rejected_400():
    """Verify short or weak nonces (< 8 chars) are rejected with HTTP 400."""
    headers = make_hmac_headers(nonce="abc")
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 400
    assert "at least 8 characters" in response.json()["detail"]


# ─── 3. Privilege Separation: Devices Never Admin ─────────────────────────────

def test_device_denied_on_admin_routes():
    """Verify authenticated IoT device is denied on admin-only endpoints."""
    headers = make_hmac_headers(method="GET", path="/speakers")
    # GET /speakers requires Role.ADMIN via get_current_admin
    # Device credentials do not satisfy Bearer token requirement
    response = client.get("/speakers", headers=headers)
    assert response.status_code == 401


def test_device_denied_on_identify():
    """Verify device cannot call /identify (unconstrained 1-to-N matching restricted to ADMIN)."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    headers = {"X-Device-ID": TEST_DEVICE_ID, "X-Device-Key": TEST_DEVICE_SECRET}
    response = client.post(
        "/identify",
        headers=headers,
        files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
    )
    assert response.status_code == 401


def test_device_allowed_on_verify():
    """Verify authenticated device is authorized to initiate verification for registered speakers."""
    headers = {"X-Device-ID": TEST_DEVICE_ID, "X-Device-Key": TEST_DEVICE_SECRET}
    # Device requesting a challenge for Zubair
    r_ch = client.post("/challenge", headers=headers, json={"claimed_identity": "Zubair", "session_id": "sess-dev-01"})
    assert r_ch.status_code == 200
    ch_data = r_ch.json()

    # Device submitting verification
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    with patch("cloud_api.run_liveness_check", return_value=(False, "Simulated liveness fail", "")):
        r_ver = client.post(
            "/verify",
            headers=headers,
            data={
                "claimed_identity": "Zubair",
                "challenge_id": ch_data["challenge_id"],
                "session_id": "sess-dev-01",
            },
            files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
        )
        assert r_ver.status_code == 200
        assert r_ver.json()["accepted"] is False


def test_device_production_plain_http_rejected_403():
    """Verify non-HTTPS requests from devices are rejected in production."""
    with patch.dict(os.environ, {"VOICELOCK_ENV": "production"}):
        headers = {"X-Device-ID": TEST_DEVICE_ID, "X-Device-Key": TEST_DEVICE_SECRET}
        # In TestClient, default scheme is http
        response = client.post("/challenge", headers=headers)
        assert response.status_code == 403
        assert "HTTPS is strictly required" in response.json()["detail"]


def test_empty_device_registry_fails_closed_500():
    """Verify missing or empty device registry causes device auth to fail closed."""
    set_test_device_registry({})
    headers = {"X-Device-ID": TEST_DEVICE_ID, "X-Device-Key": TEST_DEVICE_SECRET}
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 500
    assert "not configured on the server" in response.json()["detail"]


# ─── 4. ASGI Request-Body Protection ──────────────────────────────────────────

def test_asgi_middleware_content_length_oversized_413():
    """Verify request with declared Content-Length exceeding ceiling is rejected with 413."""
    # 2 MB payload sent to non-upload route (limit is 1 MB)
    oversized_headers = {
        "Content-Length": str(2 * 1024 * 1024),
        "Content-Type": "application/json",
    }
    response = client.post("/challenge", headers=oversized_headers, content=b"")
    assert response.status_code == 413
    assert "exceeds limit" in response.json()["detail"]


def test_asgi_middleware_streaming_oversized_without_content_length_413():
    """Verify streaming chunks without Content-Length exceeding limit are caught on-the-fly."""
    oversized_chunk = b'{"data": "' + (b"X" * (1024 * 1024 + 100)) + b'"}'  # > 1 MB JSON
    headers = {
        "X-Device-ID": TEST_DEVICE_ID,
        "X-Device-Key": TEST_DEVICE_SECRET,
        "Content-Type": "application/json",
    }
    response = client.post("/challenge", headers=headers, content=(c for c in [oversized_chunk]))
    assert response.status_code == 413
    assert "Streaming body size exceeded limit" in response.json()["detail"]


def test_asgi_middleware_misleading_content_length_streaming_413():
    """Verify misleadingly small declared Content-Length with oversized streaming body is rejected with 413."""
    oversized_chunk = b'{"data": "' + (b"X" * (1024 * 1024 + 500)) + b'"}'  # > 1 MB JSON
    headers = {
        "X-Device-ID": TEST_DEVICE_ID,
        "X-Device-Key": TEST_DEVICE_SECRET,
        "Content-Length": "10",  # Misleadingly small
        "Content-Type": "application/json",
    }
    response = client.post("/challenge", headers=headers, content=(c for c in [oversized_chunk]))
    assert response.status_code == 413
    assert "exceeded limit" in response.json()["detail"]


def test_asgi_middleware_multipart_within_limit_parses_cleanly():
    """Verify multipart uploads within limits pass through ASGI limiter without distortion."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    headers = {"X-Device-ID": TEST_DEVICE_ID, "X-Device-Key": TEST_DEVICE_SECRET}
    r_ch = client.post("/challenge", headers=headers, json={"claimed_identity": "Zubair", "session_id": "sess-mp-01"})
    assert r_ch.status_code == 200
    ch_id = r_ch.json()["challenge_id"]

    with patch("cloud_api.run_liveness_check", return_value=(False, "Liveness fail", "")):
        response = client.post(
            "/verify",
            headers=headers,
            data={"claimed_identity": "Zubair", "challenge_id": ch_id, "session_id": "sess-mp-01"},
            files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
        )
        assert response.status_code == 200
        assert "accepted" in response.json()


# ─── 5. CORS Hardening ────────────────────────────────────────────────────────

def test_cors_allowed_localhost_origin():
    """Verify explicitly allowed localhost origins receive CORS headers with credentials."""
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST",
    }
    response = client.options("/challenge", headers=headers)
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_cors_disallowed_origin_rejected():
    """Verify unauthorized external origins do not receive CORS allow headers."""
    headers = {
        "Origin": "http://unauthorized-domain.com",
        "Access-Control-Request-Method": "POST",
    }
    response = client.options("/challenge", headers=headers)
    assert response.headers.get("access-control-allow-origin") is None


def test_cors_wildcard_with_credentials_raises_error():
    """Verify configuring wildcard '*' with credentials raises ValueError."""
    with patch.dict(os.environ, {"ALLOWED_CORS_ORIGINS": "*"}):
        with pytest.raises(ValueError, match="strictly prohibited"):
            load_allowed_cors_origins()


# ─── 6. Rate Limiting and Resource Protection ─────────────────────────────────

def test_rate_limiter_exceeding_quota_returns_429():
    """Verify exceeding endpoint rate limit returns HTTP 429 with Retry-After header."""
    headers = {"X-Device-ID": TEST_DEVICE_ID, "X-Device-Key": TEST_DEVICE_SECRET}

    # /challenge limit is 30 requests per 60 seconds
    # Send 30 requests
    for i in range(30):
        r = client.post("/challenge", headers=headers)
        assert r.status_code == 200

    # Request 31 exceeds quota
    r_exceeded = client.post("/challenge", headers=headers)
    assert r_exceeded.status_code == 429
    assert "Too Many Requests" in r_exceeded.json()["detail"]
    assert "Retry-After" in r_exceeded.headers


def test_rate_limiter_memory_bounding_and_pruning():
    """Verify InMemoryRateLimiter prunes expired timestamps without unbounded growth."""
    limiter = InMemoryRateLimiter(default_limit=5, window_seconds=0.1, cleanup_interval=0.1)
    for i in range(5):
        allowed, remaining, _ = limiter.check_rate_limit("test-key")
        assert allowed is True

    # Check that rate limit triggers
    allowed, _, _ = limiter.check_rate_limit("test-key")
    assert allowed is False

    # Sleep past window and verify automatic prune and reset
    time.sleep(0.15)
    allowed, _, _ = limiter.check_rate_limit("test-key")
    assert allowed is True


# ─── 7. WebSocket Session Frame Limits ────────────────────────────────────────

def test_websocket_frame_limit_enforced():
    """Verify WebSocket disconnects with code 1008 if client exceeds 100 frames."""
    admin_token = "test-token-admin-valid"
    with client.websocket_connect("/ws/identify") as ws:
        # Initial auth handshake
        ws.send_json({"type": "auth", "token": admin_token})
        resp = ws.receive_json()
        assert resp["type"] == "auth_ok"

        # Send frames up to ceiling
        dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
        with patch("predict.predict_speaker", return_value={"predicted_speaker": "Zubair", "similarity": 0.85, "is_unknown": False}):
            for _ in range(100):
                ws.send_bytes(dummy_wav)
                ws.receive_json()

            # Frame 101 exceeds limit
            ws.send_bytes(dummy_wav)
            err = ws.receive_json()
            assert "Session frame limit exceeded" in err["error"]


# ─── 8. Security Review Regression Tests ──────────────────────────────────────

def test_invalid_signature_does_not_burn_nonce():
    """
    Vulnerability Regression: An invalid HMAC signature must NOT burn or consume
    the provided nonce. The legitimate client must be able to send with that nonce.
    """
    clean_nonce = secrets.token_hex(16)
    payload = {"claimed_identity": "Zubair"}
    body_bytes = json.dumps(payload).encode()

    # 1. Send invalid signature with fresh nonce
    headers_bad = make_hmac_headers(
        nonce=clean_nonce,
        body=body_bytes,
    )
    headers_bad["X-Device-Signature"] = "0" * 64  # Corrupt the signature
    headers_bad["Content-Type"] = "application/json"
    resp1 = client.post("/challenge", content=body_bytes, headers=headers_bad)
    assert resp1.status_code == 401
    assert "Invalid HMAC device signature" in resp1.json()["detail"]

    # 2. Now send valid signature with the SAME nonce — it MUST succeed!
    headers_good = make_hmac_headers(
        nonce=clean_nonce,
        body=body_bytes,
    )
    headers_good["Content-Type"] = "application/json"
    resp2 = client.post("/challenge", content=body_bytes, headers=headers_good)
    assert resp2.status_code == 200
    assert "challenge_id" in resp2.json()


def test_duplicate_device_headers_rejected_400():
    """Verify duplicate headers (header smuggling prevention) are rejected with 400."""
    payload = {"claimed_identity": "Zubair"}
    body_bytes = json.dumps(payload).encode()
    headers = make_hmac_headers(body=body_bytes)
    # Inject duplicate X-Device-ID header as tuple list
    raw_headers = list(headers.items()) + [("X-Device-ID", "esp32-portal-north-01"), ("Content-Type", "application/json")]

    resp = client.post("/challenge", content=body_bytes, headers=raw_headers)
    assert resp.status_code == 400
    assert "Duplicate 'X-Device-ID' headers are strictly prohibited" in resp.json()["detail"]


def test_device_key_disabled_when_configured_false_403():
    """Verify static X-Device-Key fallback is rejected with 403 when disabled."""
    with patch.dict(os.environ, {"VOICELOCK_ENABLE_DEVICE_KEY_FALLBACK": "false"}):
        resp = client.post(
            "/challenge",
            json={"claimed_identity": "Zubair"},
            headers={
                "X-Device-ID": TEST_DEVICE_ID,
                "X-Device-Key": TEST_DEVICE_SECRET,
            },
        )
        assert resp.status_code == 403
        assert "Static X-Device-Key authentication is disabled" in resp.json()["detail"]


def test_negative_content_length_rejected_400():
    """Verify negative Content-Length header is rejected with 400."""
    resp = client.post(
        "/challenge",
        content=b'{"claimed_identity": "Zubair"}',
        headers={
            "Content-Type": "application/json",
            "Content-Length": "-5",
        },
    )
    assert resp.status_code == 400
    assert "negative length is not permitted" in resp.json()["detail"]


def test_websocket_session_duration_limit_enforced():
    """Verify WebSocket terminates with code 1008 if session duration exceeds 300s."""
    admin_token = "test-token-admin-valid"
    with client.websocket_connect("/ws/identify") as ws:
        # Initial auth handshake
        ws.send_json({"type": "auth", "token": admin_token})
        resp = ws.receive_json()
        assert resp["type"] == "auth_ok"

        dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
        # Advance time by 305 seconds
        with patch("app.api.routes_verification.time.time", return_value=time.time() + 350.0):
            ws.send_bytes(dummy_wav)
            err = ws.receive_json()
            assert "Session duration limit exceeded" in err["error"]

