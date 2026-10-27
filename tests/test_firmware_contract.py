"""
tests/test_firmware_contract.py — Host-Side Contract & Verification Tests for ESP32 Firmware Client.

Validates:
1. Exact request body representation: verifies that '{"claimed_identity":"<speaker>"}'
   produced by device_auth_client.cpp hashes to the identical SHA-256 digest on the server.
2. Canonical string formatting and HMAC-SHA256 signature verification matching the firmware client.
3. Timestamp drift boundary validation (SNTP synchronization tolerance).
4. Response schema alignment: validates that ChallengeResponse matches the fields extracted by ArduinoJson.
5. Azure Container Apps Root CA alignment: verifies that root_ca.h contains DigiCert Global Root G2.
"""

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import ssl
import time
from typing import Dict, Generator, Tuple
import urllib.request

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import sessionmaker

from app.core.device_auth import set_test_device_registry, hash_device_secret, get_nonce_store
from app.db.base import Base, SpeakerRecord
from app.db.session import create_db_engine, get_db
from app.main import app
from app.repositories.speaker_repository import SpeakerRepository
from scripts.register_device import register_device


LOCAL_FIRMWARE = Path(__file__).resolve().parent.parent / "firmware"
IOT_FIRMWARE = Path("/Users/zubair/Projects/iot/voice-lock/voice-lock")
FIRMWARE_ROOT = LOCAL_FIRMWARE if LOCAL_FIRMWARE.exists() else IOT_FIRMWARE


def compute_firmware_hmac_headers(
    device_id: str,
    secret: str,
    method: str,
    path: str,
    body_str: str,
    timestamp: float = None,
    nonce: str = None,
) -> Tuple[Dict[str, str], str, str]:
    """Mirror the exact C++ formatting in device_auth_client.cpp."""
    now = time.time() if timestamp is None else timestamp
    ts_str = str(int(now))
    nonce_str = "a1b2c3d4e5f60718" if nonce is None else str(nonce)

    raw_body = body_str.encode("utf-8")
    body_sha256 = hashlib.sha256(raw_body).hexdigest()

    canonical = f"{method.upper()}\n{path}\n{ts_str}\n{nonce_str}\n{body_sha256}"
    sig = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    headers = {
        "X-Device-ID": device_id,
        "X-Device-Timestamp": ts_str,
        "X-Device-Nonce": nonce_str,
        "X-Device-Signature": sig,
        "Content-Type": "application/json",
    }
    return headers, canonical, body_sha256


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    db_path = tmp_path / "firmware_contract.db"
    db_url = f"sqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", db_url)
    from app.db.session import reset_engine
    reset_engine()

    engine = create_db_engine(db_url)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)

    import numpy as np
    with session_factory() as s:
        repo = SpeakerRepository(s)
        repo.create(
            speaker_id="Zubair",
            full_name="Zubair",
            status="active",
            embedding=np.zeros(192, dtype=np.float32),
        )
        s.commit()

    device_id = "terminal-esp32-s3-test"
    reg = register_device(db_url=db_url, device_id=device_id, name="ESP32 Test Terminal")
    secret = reg["secret"]
    set_test_device_registry({device_id: {"secret": secret, "name": "ESP32 Test Terminal"}})
    get_nonce_store().reset_for_testing()

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    yield device_id, secret

    app.dependency_overrides.pop(get_db, None)
    set_test_device_registry(None)
    reset_engine()
    engine.dispose()


class TestFirmwareContract:
    def test_firmware_canonical_signing_and_body_sha256_success(self, test_env):
        """Verify the exact JSON string and HMAC algorithm used by the firmware."""
        device_id, secret = test_env
        client = TestClient(app)

        # Exact body built in device_auth_client.cpp: snprintf(body, sizeof(body), "{\"claimed_identity\":\"%s\"}", ...)
        body_str = '{"claimed_identity":"Zubair"}'
        headers, canonical, body_digest = compute_firmware_hmac_headers(
            device_id=device_id,
            secret=secret,
            method="POST",
            path="/challenge",
            body_str=body_str,
        )

        response = client.post("/challenge", content=body_str.encode("utf-8"), headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()

        # Check required schema fields expected by ArduinoJson in firmware
        assert "challenge_id" in data
        assert "digits" in data
        assert isinstance(data["digits"], list)
        assert len(data["digits"]) == 3
        assert "display" in data
        assert "expires_in_seconds" in data
        assert data["expires_in_seconds"] == 60

    def test_firmware_sntp_clock_drift_enforcement(self, test_env):
        """Verify server rejects requests with stale or unsynchronized timestamps (>300s drift)."""
        device_id, secret = test_env
        client = TestClient(app)

        body_str = '{"claimed_identity":"Zubair"}'
        stale_time = time.time() - 600.0  # 10 minutes in past (> 300s limit)
        headers, _, _ = compute_firmware_hmac_headers(
            device_id=device_id,
            secret=secret,
            method="POST",
            path="/challenge",
            body_str=body_str,
            timestamp=stale_time,
        )

        response = client.post("/challenge", content=body_str.encode("utf-8"), headers=headers)
        assert response.status_code == 401
        assert "acceptable tolerance window" in response.json().get("detail", "")

    def test_root_ca_contains_digicert_global_root_g2(self):
        """Verify that root_ca.h in firmware contains the valid DigiCert Global Root G2 certificate."""
        root_ca_file = FIRMWARE_ROOT / "include" / "root_ca.h"
        assert root_ca_file.is_file(), f"Missing root_ca.h at {root_ca_file}"

        content = root_ca_file.read_text(encoding="utf-8")
        assert "DigiCert Global Root G2" in content
        assert "BEGIN CERTIFICATE" in content
        assert "END CERTIFICATE" in content

    def test_device_config_loader_preserves_safety(self):
        """Verify device_config_loader.h falls back safely when device_config.h is absent."""
        loader_file = FIRMWARE_ROOT / "include" / "device_config_loader.h"
        assert loader_file.is_file()
        content = loader_file.read_text(encoding="utf-8")
        assert '__has_include("device_config.h")' in content
        assert "device_config.example.h" in content
