"""
tests/test_device_auth_database.py — Test suite for Database-Backed Device Authentication Integration (Milestone 3C.3c).

Validates:
1. Valid registered active device authenticating via HMAC-SHA256 scheme.
2. Valid registered active device authenticating via pre-shared X-Device-Key scheme.
3. Unknown device rejected with HTTP 401.
4. Revoked device rejected with HTTP 401 ("Device has been revoked.").
5. Suspended device rejected with HTTP 401 ("Device is suspended.").
6. Invalid HMAC signature on registered device rejected with HTTP 401.
7. Replay attempt using duplicate nonce rejected with HTTP 401.
8. Stale timestamp outside tolerance window rejected with HTTP 401.
9. Database lookup failure fails closed with sanitized HTTP 500.
10. Separation of privileges: Device permitted on /challenge and /verify, denied on /speakers.
11. Secret mismatch: Provisioned signing key mismatching registered secret_hash rejected with HTTP 401.
12. Secrets hygiene: Database record stores only one-way cryptographic hash, never plaintext.
"""

import hashlib
import hmac
import secrets
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.base import Base, DeviceRecord
from app.db.session import create_db_engine, reset_engine
from app.repositories.device_repository import DeviceRepository
from app.core.device_auth import (
    hash_device_secret,
    get_nonce_store,
    set_test_device_registry,
)
from app.core.rate_limit import _challenge_limiter, _verify_limiter, _identify_limiter

client = TestClient(app)

TEST_DB_DEVICE_ID = "esp32-door-portal-101"
TEST_DB_SECRET = "supersecret-portal-key-32-bytes!"
TEST_DB_SECRET_HASH = hash_device_secret(TEST_DB_SECRET)


def make_device_hmac_headers(
    device_id: str = TEST_DB_DEVICE_ID,
    secret: str = TEST_DB_SECRET,
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


@pytest.fixture(autouse=True)
def setup_database_device_auth(monkeypatch):
    """Set up an isolated disposable SQLite database with head schema for each test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        tmp_db_path = Path(tmp_file.name)

    disposable_url = f"sqlite:///{tmp_db_path}"
    monkeypatch.setenv("DATABASE_URL", disposable_url)
    reset_engine()

    engine = create_db_engine(disposable_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()

    # Seed active test device in database
    repo = DeviceRepository(session)
    repo.create(
        device_id=TEST_DB_DEVICE_ID,
        secret_hash=TEST_DB_SECRET_HASH,
        name="Main Entrance Portal",
        status="active",
        key_version=1,
    )
    session.commit()

    # Configure server-side signing secret in registry for HMAC
    set_test_device_registry({
        TEST_DB_DEVICE_ID: {
            "secret": TEST_DB_SECRET,
            "name": "Main Entrance Portal",
        }
    })

    # Reset nonce store and rate limiters
    get_nonce_store().reset_for_testing()
    _challenge_limiter.reset_for_testing()
    _verify_limiter.reset_for_testing()
    _identify_limiter.reset_for_testing()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        reset_engine()
        if tmp_db_path.exists():
            try:
                tmp_db_path.unlink()
            except OSError:
                pass


def test_registered_active_device_hmac_auth_success():
    """Verify registered active device in DB authenticates successfully via HMAC."""
    headers = make_device_hmac_headers(path="/challenge")
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "challenge_id" in data
    assert "digits" in data


def test_registered_active_device_key_auth_success(setup_database_device_auth):
    """Verify registered active device in DB authenticates successfully via X-Device-Key."""
    # Seed a distinct device without registry entry to prove DB-only authentication
    session = setup_database_device_auth
    repo = DeviceRepository(session)
    psk_device_id = "esp32-standalone-psk"
    psk_secret = "standalone-psk-key-value-12345"
    repo.create(
        device_id=psk_device_id,
        secret_hash=hash_device_secret(psk_secret),
        name="Side Gate PSK",
        status="active",
    )
    session.commit()

    headers = {"X-Device-ID": psk_device_id, "X-Device-Key": psk_secret}
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "challenge_id" in data


def test_unknown_device_rejected_401():
    """Verify unregistered device ID is rejected with HTTP 401."""
    headers = make_device_hmac_headers(device_id="unknown-device-999")
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 401
    assert "unknown device identifier" in response.json()["detail"]


def test_revoked_device_rejected_401(setup_database_device_auth):
    """Verify revoked device in DB is rejected with HTTP 401 even with valid credentials."""
    session = setup_database_device_auth
    repo = DeviceRepository(session)
    repo.revoke(TEST_DB_DEVICE_ID)
    session.commit()

    headers = make_device_hmac_headers(path="/challenge")
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 401
    assert "Device has been revoked" in response.json()["detail"]


def test_suspended_device_rejected_401(setup_database_device_auth):
    """Verify suspended device in DB is rejected with HTTP 401 even with valid credentials."""
    session = setup_database_device_auth
    repo = DeviceRepository(session)
    repo.update(TEST_DB_DEVICE_ID, status="suspended")
    session.commit()

    headers = make_device_hmac_headers(path="/challenge")
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 401
    assert "Device is suspended" in response.json()["detail"]


def test_invalid_hmac_signature_on_registered_device_rejected_401():
    """Verify invalid HMAC signature on registered device is rejected with HTTP 401."""
    headers = make_device_hmac_headers(path="/challenge", secret="wrong-secret-corrupt-signature")
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 401
    assert "Invalid HMAC device signature" in response.json()["detail"]


def test_replay_attack_on_registered_device_rejected_401():
    """Verify replaying the same nonce on a registered device is rejected with HTTP 401."""
    fixed_nonce = "fixednonce123456"
    headers = make_device_hmac_headers(path="/challenge", nonce=fixed_nonce)

    # First request succeeds
    r1 = client.post("/challenge", headers=headers)
    assert r1.status_code == 200

    # Second request with identical nonce is rejected
    r2 = client.post("/challenge", headers=headers)
    assert r2.status_code == 401
    assert "Replay attack detected" in r2.json()["detail"]


def test_stale_timestamp_on_registered_device_rejected_401():
    """Verify request with timestamp outside tolerance window is rejected with HTTP 401."""
    stale_ts = time.time() - 400  # 400s drift (limit is 300s)
    headers = make_device_hmac_headers(path="/challenge", timestamp=stale_ts)
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 401
    assert "tolerance window" in response.json()["detail"]


def test_database_failure_fails_closed_500():
    """Verify database lookup failure during device auth fails closed with HTTP 500."""
    headers = make_device_hmac_headers(path="/challenge")
    with patch.object(DeviceRepository, "get_by_device_id", side_effect=Exception("Database connection timeout")):
        response = client.post("/challenge", headers=headers)
        assert response.status_code == 500
        assert "Database device authentication service unavailable" in response.json()["detail"]


def test_device_authorization_separation():
    """Verify authenticated device is permitted on /challenge but denied on admin endpoints."""
    headers = make_device_hmac_headers(path="/challenge")
    r_ch = client.post("/challenge", headers=headers)
    assert r_ch.status_code == 200

    # Device attempts to list speakers -> HTTP 401 Unauthorized (requires Role.ADMIN via Bearer token)
    headers_spk = make_device_hmac_headers(path="/speakers", method="GET")
    r_spk = client.get("/speakers", headers=headers_spk)
    assert r_spk.status_code == 401


def test_tampered_secret_hash_rejected_401(setup_database_device_auth):
    """Verify that if database secret_hash does not match signing secret, auth is rejected."""
    session = setup_database_device_auth
    repo = DeviceRepository(session)
    repo.update(TEST_DB_DEVICE_ID, metadata_json=None)
    # Alter secret_hash in database to a different hash
    record = repo.get_by_device_id(TEST_DB_DEVICE_ID)
    record.secret_hash = hash_device_secret("different-secret-entirely")
    session.commit()

    headers = make_device_hmac_headers(path="/challenge")
    response = client.post("/challenge", headers=headers)
    assert response.status_code == 401
    assert "Invalid device credentials" in response.json()["detail"]


def test_raw_secrets_never_stored_or_leaked(setup_database_device_auth):
    """Verify database record never stores plaintext secrets or keys."""
    session = setup_database_device_auth
    repo = DeviceRepository(session)
    record = repo.get_by_device_id(TEST_DB_DEVICE_ID)

    assert record is not None
    assert record.secret_hash.startswith("sha256$")
    assert TEST_DB_SECRET not in record.secret_hash
    assert len(record.secret_hash) == 7 + 64
