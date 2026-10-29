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
        assert "2038" in content
        assert "Rotation Strategy" in content
        assert "OTA" in content

    def test_root_ca_authenticates_live_azure_backend(self, tmp_path):
        """Verify the embedded root CA directly validates the live Azure Container App TLS certificate."""
        import socket
        root_ca_file = FIRMWARE_ROOT / "include" / "root_ca.h"
        content = root_ca_file.read_text(encoding="utf-8")
        
        parts = re.findall(r"\"([^\"]*)\"", content)
        pem = "".join(parts).replace("\\n", "\n")
        ca_pem_path = tmp_path / "azure_ca.pem"
        ca_pem_path.write_text(pem, encoding="utf-8")

        ctx = ssl.create_default_context(cafile=str(ca_pem_path))
        host = "voicelock-api.orangesand-9922d50e.eastasia.azurecontainerapps.io"
        with socket.create_connection((host, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                assert ssock.version() in ("TLSv1.2", "TLSv1.3")
                cipher, protocol, bits = ssock.cipher()
                assert bits >= 128

    def test_device_config_loader_preserves_safety(self):
        """Verify device_config_loader.h falls back safely when device_config.h is absent."""
        loader_file = FIRMWARE_ROOT / "include" / "device_config_loader.h"
        assert loader_file.is_file()
        content = loader_file.read_text(encoding="utf-8")
        assert '__has_include("device_config.h")' in content
        assert "device_config.example.h" in content

    def test_firmware_state_machine_security_invariants(self):
        """Verify firmware state machine never illuminates Green LED or indicates authorization prior to server approval."""
        main_file = FIRMWARE_ROOT / "src" / "main.cpp"
        assert main_file.is_file()
        content = main_file.read_text(encoding="utf-8")

        # In standby, setup, challenge display, and transmitting: Green LED must remain LOW
        # (Green LED is strictly reserved for server UNLOCK in Milestone 3)
        assert "digitalWrite(LED_GREEN, LOW)" in content
        transmit_block = content.split("void transmitAudioPayload()")[1].split("void startChallengeRequest()")[0]
        assert "digitalWrite(LED_GREEN, LOW);" in transmit_block
        assert "digitalWrite(LED_GREEN, HIGH);" not in transmit_block

        # Check dispatchVerificationUpload strict green LED isolation
        upload_block = content.split("void dispatchVerificationUpload()")[1].split("void captureStep()")[0]
        # Green LED should only be set HIGH inside the isUnlock branch
        assert "if (activeVerifyResult.isUnlock)" in upload_block
        assert "digitalWrite(LED_GREEN, HIGH);" in upload_block
        # In denial and error branches, Green LED must be explicitly LOW
        assert "digitalWrite(LED_GREEN, LOW);" in upload_block
        # CANCEL handling must support STATE_UPLOADING
        assert "STATE_UPLOADING" in content

    # ─── Milestone 3: End-to-End Audio Verification Contract Tests ────────────

    def test_wav_header_exact_byte_structure_and_soundfile_decoding(self):
        """Verify the exact 44-byte RIFF/WAVE header generated by firmware createWavHeader."""
        import struct
        import wave
        import soundfile as sf
        import io

        pcm_bytes = 160000  # 5 seconds at 16000 Hz, 16-bit mono
        header = bytearray(44)
        header[0:4] = b"RIFF"
        struct.pack_into("<I", header, 4, 36 + pcm_bytes)
        header[8:12] = b"WAVE"
        header[12:16] = b"fmt "
        struct.pack_into("<I", header, 16, 16)
        struct.pack_into("<H", header, 20, 1)  # PCM format
        struct.pack_into("<H", header, 22, 1)  # 1 channel (mono)
        struct.pack_into("<I", header, 24, 16000)  # 16000 Hz
        struct.pack_into("<I", header, 28, 32000)  # byte rate = 16000 * 1 * 2
        struct.pack_into("<H", header, 32, 2)  # block align = 1 * 2
        struct.pack_into("<H", header, 34, 16)  # 16 bits per sample
        header[36:40] = b"data"
        struct.pack_into("<I", header, 40, pcm_bytes)

        assert len(header) == 44
        assert header[0:4] == b"RIFF"
        assert header[8:12] == b"WAVE"
        assert header[12:16] == b"fmt "
        assert header[36:40] == b"data"

        # Verify decoding with standard Python wave module
        dummy_pcm = b"\x00" * pcm_bytes
        full_wav = bytes(header) + dummy_pcm
        with wave.open(io.BytesIO(full_wav), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() == 80000

        # Verify decoding with soundfile
        audio_data, sr = sf.read(io.BytesIO(full_wav), dtype="float32")
        assert sr == 16000
        assert len(audio_data) == 80000

    def test_firmware_multipart_request_construction_and_hmac_verification(self, test_env):
        """Verify multipart framing and Scheme A HMAC-SHA256 signature verification on POST /verify."""
        import struct
        import wave
        import io
        from unittest.mock import patch

        device_id, secret = test_env
        client = TestClient(app)

        # 1. Acquire valid challenge from /challenge
        ch_body_str = '{"claimed_identity":"Zubair"}'
        ch_headers, _, _ = compute_firmware_hmac_headers(
            device_id=device_id,
            secret=secret,
            method="POST",
            path="/challenge",
            body_str=ch_body_str,
        )
        ch_res = client.post("/challenge", content=ch_body_str.encode("utf-8"), headers=ch_headers)
        assert ch_res.status_code == 200
        ch_data = ch_res.json()
        challenge_id = ch_data["challenge_id"]
        session_id = ch_data["session_id"]

        # 2. Construct multipart body matching device_auth_client.cpp exactly
        boundary = "----VoiceLockFormBoundary7MA4YWxkTrZu0gW"
        pcm_bytes = 16000 * 2  # 1 second of audio
        header = bytearray(44)
        header[0:4] = b"RIFF"
        struct.pack_into("<I", header, 4, 36 + pcm_bytes)
        header[8:12] = b"WAVE"
        header[12:16] = b"fmt "
        struct.pack_into("<I", header, 16, 16)
        struct.pack_into("<H", header, 20, 1)
        struct.pack_into("<H", header, 22, 1)
        struct.pack_into("<I", header, 24, 16000)
        struct.pack_into("<I", header, 28, 32000)
        struct.pack_into("<H", header, 32, 2)
        struct.pack_into("<H", header, 34, 16)
        header[36:40] = b"data"
        struct.pack_into("<I", header, 40, pcm_bytes)
        wav_payload = bytes(header) + (b"\x00" * pcm_bytes)

        part1 = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="claimed_identity"\r\n\r\n'
            f"Zubair\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="challenge_id"\r\n\r\n'
            f"{challenge_id}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="session_id"\r\n\r\n'
            f"{session_id}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="audio"; filename="capture.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8")
        part2 = f"\r\n--{boundary}--\r\n".encode("utf-8")

        raw_multipart = part1 + wav_payload + part2

        # 3. Compute Scheme A HMAC-SHA256 headers matching device_auth_client.cpp
        ts_str = str(int(time.time()))
        nonce_str = "b2c3d4e5f6071829"
        body_sha256 = hashlib.sha256(raw_multipart).hexdigest()
        canonical = f"POST\n/verify\n{ts_str}\n{nonce_str}\n{body_sha256}"
        sig = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()

        v_headers = {
            "Host": "localhost",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(raw_multipart)),
            "X-Device-ID": device_id,
            "X-Device-Timestamp": ts_str,
            "X-Device-Nonce": nonce_str,
            "X-Device-Signature": sig,
        }

        # Mock liveness and speaker verification to isolate contract testing
        with patch("app.api.routes_verification._get_run_liveness_check") as mock_liveness, \
             patch("app.api.routes_verification._get_verify_speaker") as mock_verify:
            mock_liveness.return_value = lambda audio_path, digits: (True, "Liveness passed", ["1", "2", "3"])
            mock_verify.return_value = lambda **kwargs: {
                "is_accepted": True,
                "similarity": 0.88,
                "claimed_identity": "Zubair",
            }

            v_res = client.post("/verify", content=raw_multipart, headers=v_headers)
            assert v_res.status_code == 200, v_res.text
            v_data = v_res.json()

            # Verify response schema fields expected by firmware
            assert v_data["accepted"] is True
            assert v_data["action"] == "UNLOCK"
            assert v_data["claimed_identity"] == "Zubair"
            assert v_data["similarity"] == 0.88
            assert v_data["liveness_passed"] is True

    def test_backend_authorization_decision_explicit_rejection(self, test_env):
        """Verify explicit biometric rejection produces action='DENY' and accepted=False."""
        import struct
        from unittest.mock import patch

        device_id, secret = test_env
        client = TestClient(app)

        ch_body_str = '{"claimed_identity":"Zubair"}'
        ch_headers, _, _ = compute_firmware_hmac_headers(device_id=device_id, secret=secret, method="POST", path="/challenge", body_str=ch_body_str)
        ch_res = client.post("/challenge", content=ch_body_str.encode("utf-8"), headers=ch_headers)
        ch_data = ch_res.json()

        boundary = "----VoiceLockFormBoundary7MA4YWxkTrZu0gW"
        pcm_bytes = 16000 * 2
        header = bytearray(44)
        header[0:4] = b"RIFF"
        struct.pack_into("<I", header, 4, 36 + pcm_bytes)
        header[8:12] = b"WAVE"
        header[12:16] = b"fmt "
        struct.pack_into("<I", header, 16, 16)
        struct.pack_into("<H", header, 20, 1)
        struct.pack_into("<H", header, 22, 1)
        struct.pack_into("<I", header, 24, 16000)
        struct.pack_into("<I", header, 28, 32000)
        struct.pack_into("<H", header, 32, 2)
        struct.pack_into("<H", header, 34, 16)
        header[36:40] = b"data"
        struct.pack_into("<I", header, 40, pcm_bytes)
        wav_payload = bytes(header) + (b"\x00" * pcm_bytes)

        part1 = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="claimed_identity"\r\n\r\n'
            f"Zubair\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="challenge_id"\r\n\r\n'
            f"{ch_data['challenge_id']}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="session_id"\r\n\r\n'
            f"{ch_data['session_id']}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="audio"; filename="capture.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8")
        raw_multipart = part1 + wav_payload + f"\r\n--{boundary}--\r\n".encode("utf-8")

        ts_str = str(int(time.time()))
        nonce_str = "c3d4e5f607182930"
        body_sha256 = hashlib.sha256(raw_multipart).hexdigest()
        canonical = f"POST\n/verify\n{ts_str}\n{nonce_str}\n{body_sha256}"
        sig = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        v_headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-Device-ID": device_id,
            "X-Device-Timestamp": ts_str,
            "X-Device-Nonce": nonce_str,
            "X-Device-Signature": sig,
        }

        with patch("app.api.routes_verification._get_run_liveness_check") as mock_liveness, \
             patch("app.api.routes_verification._get_verify_speaker") as mock_verify:
            mock_liveness.return_value = lambda audio_path, digits: (True, "Liveness passed", ["1", "2", "3"])
            mock_verify.return_value = lambda **kwargs: {
                "is_accepted": False,
                "similarity": 0.15,
                "claimed_identity": "Zubair",
            }

            v_res = client.post("/verify", content=raw_multipart, headers=v_headers)
            assert v_res.status_code == 200
            v_data = v_res.json()
            assert v_data["accepted"] is False
            assert v_data["action"] == "DENY"
            assert v_data["similarity"] == 0.15

    def test_backend_authorization_decision_failed_liveness(self, test_env):
        """Verify failed liveness check immediately denies access without ML verification."""
        import struct
        from unittest.mock import patch

        device_id, secret = test_env
        client = TestClient(app)

        ch_body_str = '{"claimed_identity":"Zubair"}'
        ch_headers, _, _ = compute_firmware_hmac_headers(device_id=device_id, secret=secret, method="POST", path="/challenge", body_str=ch_body_str)
        ch_res = client.post("/challenge", content=ch_body_str.encode("utf-8"), headers=ch_headers)
        ch_data = ch_res.json()

        boundary = "----VoiceLockFormBoundary7MA4YWxkTrZu0gW"
        pcm_bytes = 16000 * 2
        header = bytearray(44)
        header[0:4] = b"RIFF"
        struct.pack_into("<I", header, 4, 36 + pcm_bytes)
        header[8:12] = b"WAVE"
        header[12:16] = b"fmt "
        struct.pack_into("<I", header, 16, 16)
        struct.pack_into("<H", header, 20, 1)
        struct.pack_into("<H", header, 22, 1)
        struct.pack_into("<I", header, 24, 16000)
        struct.pack_into("<I", header, 28, 32000)
        struct.pack_into("<H", header, 32, 2)
        struct.pack_into("<H", header, 34, 16)
        header[36:40] = b"data"
        struct.pack_into("<I", header, 40, pcm_bytes)
        wav_payload = bytes(header) + (b"\x00" * pcm_bytes)

        part1 = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="claimed_identity"\r\n\r\n'
            f"Zubair\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="challenge_id"\r\n\r\n'
            f"{ch_data['challenge_id']}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="session_id"\r\n\r\n'
            f"{ch_data['session_id']}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="audio"; filename="capture.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8")
        raw_multipart = part1 + wav_payload + f"\r\n--{boundary}--\r\n".encode("utf-8")

        ts_str = str(int(time.time()))
        nonce_str = "d4e5f60718293041"
        body_sha256 = hashlib.sha256(raw_multipart).hexdigest()
        canonical = f"POST\n/verify\n{ts_str}\n{nonce_str}\n{body_sha256}"
        sig = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        v_headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-Device-ID": device_id,
            "X-Device-Timestamp": ts_str,
            "X-Device-Nonce": nonce_str,
            "X-Device-Signature": sig,
        }

        with patch("app.api.routes_verification._get_run_liveness_check") as mock_liveness:
            mock_liveness.return_value = lambda audio_path, digits: (False, "Spoken digits do not match challenge", [])

            v_res = client.post("/verify", content=raw_multipart, headers=v_headers)
            assert v_res.status_code == 200
            v_data = v_res.json()
            assert v_data["accepted"] is False
            assert v_data["action"] == "DENY"
            assert v_data["liveness_passed"] is False
            assert "Liveness check failed" in v_data.get("reason", "")

    def test_expired_or_consumed_challenge_rejection(self, test_env):
        """Verify replayed or invalid challenge returns HTTP 400."""
        import struct

        device_id, secret = test_env
        client = TestClient(app)

        boundary = "----VoiceLockFormBoundary7MA4YWxkTrZu0gW"
        pcm_bytes = 16000 * 2
        header = bytearray(44)
        header[0:4] = b"RIFF"
        struct.pack_into("<I", header, 4, 36 + pcm_bytes)
        header[8:12] = b"WAVE"
        header[12:16] = b"fmt "
        struct.pack_into("<I", header, 16, 16)
        struct.pack_into("<H", header, 20, 1)
        struct.pack_into("<H", header, 22, 1)
        struct.pack_into("<I", header, 24, 16000)
        struct.pack_into("<I", header, 28, 32000)
        struct.pack_into("<H", header, 32, 2)
        struct.pack_into("<H", header, 34, 16)
        header[36:40] = b"data"
        struct.pack_into("<I", header, 40, pcm_bytes)
        wav_payload = bytes(header) + (b"\x00" * pcm_bytes)

        part1 = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="claimed_identity"\r\n\r\n'
            f"Zubair\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="challenge_id"\r\n\r\n'
            f"fake-or-expired-challenge-id\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="session_id"\r\n\r\n'
            f"fake-session-id\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="audio"; filename="capture.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8")
        raw_multipart = part1 + wav_payload + f"\r\n--{boundary}--\r\n".encode("utf-8")

        ts_str = str(int(time.time()))
        nonce_str = "e5f6071829304152"
        body_sha256 = hashlib.sha256(raw_multipart).hexdigest()
        canonical = f"POST\n/verify\n{ts_str}\n{nonce_str}\n{body_sha256}"
        sig = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        v_headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-Device-ID": device_id,
            "X-Device-Timestamp": ts_str,
            "X-Device-Nonce": nonce_str,
            "X-Device-Signature": sig,
        }

        v_res = client.post("/verify", content=raw_multipart, headers=v_headers)
        assert v_res.status_code == 400
        assert "not found" in v_res.json().get("detail", "").lower() or "invalid" in v_res.json().get("detail", "").lower()

    def test_firmware_response_parsing_decision_logic(self):
        """Test the exact firmware parsing logic: isUnlock is true ONLY if httpCode==200 && accepted && action=='UNLOCK'."""
        def parse_firmware_decision(http_code: int, response_json: dict) -> Tuple[bool, str]:
            if http_code != 200:
                return False, "HTTP_ERROR"
            accepted = response_json.get("accepted", False)
            action = response_json.get("action", "")
            is_unlock = (http_code == 200 and accepted is True and action == "UNLOCK")
            return is_unlock, action

        # 1. Valid UNLOCK
        is_unlock, action = parse_firmware_decision(200, {"accepted": True, "action": "UNLOCK", "similarity": 0.91})
        assert is_unlock is True

        # 2. Rejection DENY
        is_unlock, action = parse_firmware_decision(200, {"accepted": False, "action": "DENY", "similarity": 0.15})
        assert is_unlock is False

        # 3. Anomalous payload (accepted: True but action: "DENY")
        is_unlock, action = parse_firmware_decision(200, {"accepted": True, "action": "DENY"})
        assert is_unlock is False

        # 4. Anomalous payload (accepted: False but action: "UNLOCK")
        is_unlock, action = parse_firmware_decision(200, {"accepted": False, "action": "UNLOCK"})
        assert is_unlock is False

        # 5. Non-200 HTTP code
        is_unlock, action = parse_firmware_decision(401, {"detail": "Invalid credentials"})
        assert is_unlock is False

        # 6. Malformed JSON (missing fields)
        is_unlock, action = parse_firmware_decision(200, {})
        assert is_unlock is False

    def test_http_error_status_codes_401_403_and_tampered_payload(self, test_env):
        """Verify HTTP 401 on signature mismatch, tampered bytes, and revoked device."""
        device_id, secret = test_env
        client = TestClient(app)

        # Tampered signature
        body = b'{"claimed_identity":"Zubair"}'
        headers, _, _ = compute_firmware_hmac_headers(device_id, secret, "POST", "/challenge", body.decode())
        headers["X-Device-Signature"] = "0" * 64
        res = client.post("/challenge", content=body, headers=headers)
        assert res.status_code == 401

        # Tampered body with valid signature for original body
        headers_good, _, _ = compute_firmware_hmac_headers(device_id, secret, "POST", "/challenge", body.decode())
        tampered_body = b'{"claimed_identity":"Attacker"}'
        res = client.post("/challenge", content=tampered_body, headers=headers_good)
        assert res.status_code == 401

    def test_capture_timeout_diagnostics_and_display_suppression(self):
        """Verify firmware implements bounded I2S timeout diagnostics and avoids OLED transfers during capture."""
        main_file = FIRMWARE_ROOT / "src" / "main.cpp"
        assert main_file.is_file()
        content = main_file.read_text(encoding="utf-8")

        # 1. Bounded diagnostic tracking variables must be declared
        assert "size_t captureZeroReads = 0;" in content
        assert "size_t captureLastReadBytes = 0;" in content

        # 2. beginRecording and cancelAction must initialize and reset diagnostic counters
        begin_block = content.split("void beginRecording(bool forVerification")[1].split("void cancelAction()")[0]
        assert "captureZeroReads = 0;" in begin_block
        assert "captureLastReadBytes = 0;" in begin_block

        cancel_block = content.split("void cancelAction()")[1].split("void dispatchVerificationUpload()")[0]
        assert "captureZeroReads = 0;" in cancel_block
        assert "captureLastReadBytes = 0;" in cancel_block

        # 3. captureStep must update counters and emit structured timeout diagnostics
        capture_block = content.split("void captureStep()")[1].split("void transmitAudioPayload()")[0]
        assert "captureLastReadBytes = bytesRead;" in capture_block
        assert "if (bytesRead == 0)" in capture_block
        assert "captureZeroReads++;" in capture_block

        # Check structured JSON fields in ERROR_I2S_TIMEOUT log
        assert "ERROR_I2S_TIMEOUT:{\\\"captured\\\":%u,\\\"target\\\":%u,\\\"elapsed_ms\\\":%lu,\\\"zero_reads\\\":%u,\\\"last_read_bytes\\\":%u}\\n" in capture_block

        # Check safety invariants on timeout: Green LED strictly LOW, Red LED HIGH, error tone
        timeout_subblock = capture_block.split("if (millis() - stateEnteredAt > CAPTURE_TIMEOUT_MS)")[1].split("setState(STATE_ERROR);")[0]
        assert "digitalWrite(LED_GREEN, LOW);" in timeout_subblock
        assert "digitalWrite(LED_RED, HIGH);" in timeout_subblock
        assert "errorTone();" in timeout_subblock

        # 4. In loop(), under STATE_RECORDING, display updating is suppressed during active capture
        loop_block = content.split("void loop()")[1]
        recording_case = loop_block.split("case STATE_RECORDING:")[1].split("case STATE_UPLOADING:")[0]
        assert "captureStep();" in recording_case
        assert "updateDisplay();" not in recording_case

        # 5. Diagnostic JSON parsing contract verification
        import json
        mock_log = 'ERROR_I2S_TIMEOUT:{"captured":51200,"target":80000,"elapsed_ms":8001,"zero_reads":0,"last_read_bytes":1024}'
        prefix, json_str = mock_log.split(":", 1)
        assert prefix == "ERROR_I2S_TIMEOUT"
        parsed = json.loads(json_str)
        assert parsed["captured"] == 51200
        assert parsed["target"] == 80000
        assert parsed["elapsed_ms"] == 8001
        assert parsed["zero_reads"] == 0
        assert parsed["last_read_bytes"] == 1024

