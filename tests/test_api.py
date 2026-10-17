"""
tests/test_api.py — Comprehensive security and contract test suite for VoiceLock FastAPI endpoints.

Covers:
- Basic health and discovery (GET /, GET /speakers)
- Real ML inference integration (identify & verify)
- Review A: Upload security (streaming limits, Content-Length pre-check, malformed audio handling, temp-file cleanup)
- Review B: Threshold security (tamper resistance, server boundary enforcement, defensive config loaders)
- Review C: Security boundary verification (no inference on oversized uploads, cleanup on failure)
- Review D: Error handling in predict.py (FileNotFoundError, empty profiles, typed exceptions)
"""

import io
import os
import tempfile
import time
import concurrent.futures
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from cloud_api import (
    app,
    MAX_AUDIO_SIZE_BYTES,
    SERVER_THRESHOLD,
    load_server_threshold,
    load_max_audio_size,
)
from predict import predict_speaker, verify_speaker, DEFAULT_THRESHOLD
from liveness import (
    default_challenge_store,
    InMemoryChallengeStore,
    ChallengeStatus,
    LivenessChallenge,
    generate_challenge,
)
from app.core.auth import get_current_user, get_current_admin, AuthenticatedUser
from app.core.auth_policy import Role

client = TestClient(app)

SAMPLE_WAV = Path(__file__).resolve().parent.parent / "processed_dataset" / "Zubair" / "Zubair_Enrollment_R01.wav"


@pytest.fixture(autouse=True)
def override_auth_dependencies():
    """Ensure baseline regression tests execute under an authenticated admin context."""
    admin_user = AuthenticatedUser(
        uid="test-admin-uid",
        email="admin@voicelock.test",
        email_verified=True,
        roles=[Role.ADMIN, Role.USER],
    )
    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_current_admin] = lambda: admin_user
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_admin, None)


# ─── Baseline Contract Tests ──────────────────────────────────────────────────

def test_root_endpoint():
    """Verify health check endpoint returns 200 and expected service status."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "online"
    assert "Speaker Recognition API" in data.get("service", "")


def test_list_speakers_endpoint():
    """Verify registered speakers listing returns 200, list, and count."""
    response = client.get("/speakers")
    assert response.status_code == 200
    data = response.json()
    assert "registered_speakers" in data
    assert isinstance(data["registered_speakers"], list)
    assert data["count"] == len(data["registered_speakers"])
    assert "Zubair" in data["registered_speakers"]


# ─── Real Inference Integration Tests ─────────────────────────────────────────

@pytest.mark.skipif(not SAMPLE_WAV.exists(), reason="Sample WAV file not found for integration test")
def test_identify_real_audio_success():
    """Integration test: submit valid Zubair recording and verify identification."""
    with open(SAMPLE_WAV, "rb") as f:
        audio_bytes = f.read()

    response = client.post(
        "/identify",
        files={"audio": ("sample.wav", io.BytesIO(audio_bytes), "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["predicted_speaker"] == "Zubair"
    assert data["similarity"] > SERVER_THRESHOLD
    assert data["is_unknown"] is False
    assert data["threshold_used"] == SERVER_THRESHOLD


@pytest.mark.skipif(not SAMPLE_WAV.exists(), reason="Sample WAV file not found for integration test")
def test_verify_real_audio_success():
    """Integration test: 1-to-1 verification with valid challenge and matching liveness."""
    ch_resp = client.post("/challenge", data={"claimed_identity": "Zubair"})
    assert ch_resp.status_code == 200
    ch_data = ch_resp.json()

    with open(SAMPLE_WAV, "rb") as f:
        audio_bytes = f.read()

    with patch("cloud_api.run_liveness_check", return_value=(True, "Liveness verified", "dummy")):
        response = client.post(
            "/verify",
            data={
                "claimed_identity": "Zubair",
                "challenge_id": ch_data["challenge_id"],
                "session_id": ch_data["session_id"],
            },
            files={"audio": ("sample.wav", io.BytesIO(audio_bytes), "audio/wav")},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] is True
    assert data["claimed_identity"] == "Zubair"
    assert data["action"] == "UNLOCK"
    assert data["threshold_used"] == SERVER_THRESHOLD
    assert data["liveness_passed"] is True


def test_verify_unknown_speaker_404():
    """Verification for an unregistered claimed identity must return 404."""
    dummy_wav = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    response = client.post(
        "/verify",
        data={
            "claimed_identity": "NonExistentUser999",
            "challenge_id": "ch_dummy",
            "session_id": "sess_dummy",
        },
        files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
    )
    assert response.status_code == 404
    assert "not registered" in response.json()["detail"].lower()


# ─── REVIEW A: Upload Security & Input Validation ─────────────────────────────

def test_missing_audio_payload():
    """Sending request without audio file must return 422 Unprocessable Entity."""
    response = client.post("/identify")
    assert response.status_code == 422


def test_empty_audio_file():
    """Sending an empty 0-byte audio file must return 400 Bad Request."""
    response = client.post(
        "/identify",
        files={"audio": ("empty.wav", io.BytesIO(b""), "audio/wav")},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_unsupported_audio_extension():
    """Sending a non-audio file (e.g. .txt, .exe) must return 400 Bad Request."""
    response = client.post(
        "/identify",
        files={"audio": ("script.sh", io.BytesIO(b"echo hello"), "text/plain")},
    )
    assert response.status_code == 400
    assert "unsupported" in response.json()["detail"].lower()


def test_oversized_audio_rejected_before_inference():
    """
    Security check: Upload exceeding MAX_AUDIO_SIZE_BYTES must return 413 Payload Too Large
    and MUST NEVER invoke ML inference.
    """
    oversized_data = b"0" * (MAX_AUDIO_SIZE_BYTES + 1024)
    with patch("cloud_api.predict_speaker") as mock_predict:
        response = client.post(
            "/identify",
            files={"audio": ("huge.wav", io.BytesIO(oversized_data), "audio/wav")},
        )
        assert response.status_code == 413
        assert "exceeds" in response.json()["detail"].lower()
        mock_predict.assert_not_called()


def test_content_length_header_precheck_rejection():
    """
    Security check: Request with Content-Length exceeding MAX_AUDIO_SIZE_BYTES
    is rejected immediately without reading the payload.
    """
    headers = {"Content-Length": str(MAX_AUDIO_SIZE_BYTES + 50000)}
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    with patch("cloud_api.predict_speaker") as mock_predict:
        response = client.post(
            "/identify",
            files={"audio": ("sample.wav", io.BytesIO(dummy_wav), "audio/wav")},
            headers=headers,
        )
        assert response.status_code == 413
        mock_predict.assert_not_called()


def test_malformed_audio_returns_400_not_500():
    """
    Security check: Non-audio content disguised as a .wav file (e.g. ASCII text)
    must return 400 Bad Request (client fault), not 500 Internal Server Error,
    and must clean up temporary files.
    """
    garbage_bytes = b"This is plain text disguised with a .wav extension."
    response = client.post(
        "/identify",
        files={"audio": ("fake.wav", io.BytesIO(garbage_bytes), "audio/wav")},
    )
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower() or "unreadable" in response.json()["detail"].lower()


# ─── REVIEW B: Threshold Configuration & Tamper Resistance ────────────────────

def test_client_threshold_tampering_cannot_bypass_denial():
    """
    Security check: An impostor voice whose similarity is 0.15 (below 0.25)
    submitting threshold=0.01 MUST STILL BE REJECTED.
    Client threshold tampering cannot flip the decision from DENY to UNLOCK.
    """
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    
    ch_resp = client.post("/challenge", data={"claimed_identity": "Zubair"})
    assert ch_resp.status_code == 200
    ch_data = ch_resp.json()

    # Mock verify_speaker to evaluate against the threshold passed to it
    def controlled_verify(audio_path, claimed_identity, threshold, **kwargs):
        sim = 0.15  # Impostor similarity
        return {
            "is_accepted": sim >= threshold,
            "similarity": sim,
            "threshold": threshold,
            "claimed_identity": claimed_identity,
        }

    with patch("cloud_api.run_liveness_check", return_value=(True, "Liveness verified", "dummy")):
        with patch("cloud_api.verify_speaker", side_effect=controlled_verify):
            response = client.post(
                "/verify",
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": ch_data["challenge_id"],
                    "session_id": ch_data["session_id"],
                    "threshold": 0.01,  # Attempting to bypass
                },
                files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["accepted"] is False
            assert data["action"] == "DENY"
            assert data["threshold_used"] == SERVER_THRESHOLD


def test_load_server_threshold_defensive_fallbacks():
    """Verify load_server_threshold fails safely when given invalid or out-of-range env vars."""
    with patch.dict(os.environ, {"DEFAULT_THRESHOLD": "not-a-number"}):
        assert load_server_threshold() == DEFAULT_THRESHOLD

    with patch.dict(os.environ, {"DEFAULT_THRESHOLD": "-0.5"}):
        assert load_server_threshold() == DEFAULT_THRESHOLD

    with patch.dict(os.environ, {"DEFAULT_THRESHOLD": "1.5"}):
        assert load_server_threshold() == DEFAULT_THRESHOLD

    with patch.dict(os.environ, {"DEFAULT_THRESHOLD": "0.45"}):
        assert load_server_threshold() == 0.45


def test_load_max_audio_size_defensive_fallbacks():
    """Verify load_max_audio_size fails safely when given invalid env vars."""
    default_bytes = 10 * 1024 * 1024

    with patch.dict(os.environ, {"MAX_AUDIO_SIZE_BYTES": "invalid"}):
        assert load_max_audio_size() == default_bytes

    with patch.dict(os.environ, {"MAX_AUDIO_SIZE_BYTES": "-100"}):
        assert load_max_audio_size() == default_bytes

    with patch.dict(os.environ, {"MAX_AUDIO_SIZE_BYTES": "5242880"}):
        assert load_max_audio_size() == 5242880


# ─── REVIEW C & D: Error Handling, Temp File Lifecycle, and predict.py ─────────

def test_inference_failure_returns_safe_500():
    """Inference exception must return 500 without leaking stack traces or internal filesystem paths."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    
    with patch("cloud_api.predict_speaker", side_effect=Exception("internal compute engine error")):
        response = client.post(
            "/identify",
            files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
        )
        assert response.status_code == 500
        detail = response.json()["detail"]
        assert "inference failed" in detail.lower()
        # Ensure raw traceback or paths are not dumped
        assert "/Users/" not in detail
        assert "Traceback" not in detail


def test_empty_profiles_handled_gracefully():
    """If profiles dictionary is empty, API returns 503 Service Unavailable without crashing."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    
    with patch("cloud_api.get_system", return_value=({}, MagicMock())):
        response = client.post(
            "/identify",
            files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
        )
        assert response.status_code == 503
        assert "no speaker profiles" in response.json()["detail"].lower()


def test_temp_file_cleanup_on_success_and_failure():
    """Verify temporary audio files are removed from disk on both successful and failed inference."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    
    created_temp_files = []
    import cloud_api
    original_save = cloud_api.save_upload

    def tracking_save(audio, request=None):
        path = original_save(audio, request=request)
        created_temp_files.append(path)
        return path

    with patch("cloud_api.save_upload", side_effect=tracking_save):
        # Case A: Success
        mock_result = {
            "predicted_speaker": "Zubair",
            "similarity": 0.85,
            "is_unknown": False,
            "all_scores": {"Zubair": 0.85},
            "threshold": SERVER_THRESHOLD,
        }
        with patch("cloud_api.predict_speaker", return_value=mock_result):
            resp = client.post(
                "/identify",
                files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
            )
            assert resp.status_code == 200

        # Case B: Failure
        with patch("cloud_api.predict_speaker", side_effect=RuntimeError("internal engine fault")):
            resp = client.post(
                "/identify",
                files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
            )
            assert resp.status_code == 500

    # Verify all tracked temporary files were unlinked
    assert len(created_temp_files) == 2
    for tmp in created_temp_files:
        assert not tmp.exists(), f"Temporary file {tmp} was not cleaned up!"


def test_predict_speaker_raises_filenotfound_on_missing_file():
    """Verify predict_speaker raises FileNotFoundError rather than calling sys.exit()."""
    with pytest.raises(FileNotFoundError) as exc_info:
        predict_speaker("nonexistent_path_test_1234.wav")
    assert "not found" in str(exc_info.value).lower()


def test_verify_speaker_raises_filenotfound_on_missing_file():
    """Verify verify_speaker raises FileNotFoundError rather than calling sys.exit()."""
    with pytest.raises(FileNotFoundError) as exc_info:
        verify_speaker("nonexistent_path_test_1234.wav", claimed_identity="Zubair")
    assert "not found" in str(exc_info.value).lower()


def test_predict_speaker_raises_valueerror_on_empty_profiles():
    """Verify predict_speaker raises ValueError when profiles dictionary is empty."""
    dummy_wav = Path(__file__).resolve().parent.parent / "processed_dataset" / "Zubair" / "Zubair_Enrollment_R01.wav"
    if dummy_wav.exists():
        with pytest.raises(ValueError) as exc_info:
            predict_speaker(str(dummy_wav), profiles={})
        assert "no speaker profiles" in str(exc_info.value).lower()


# ─── MILESTONE 2B: Stateful Liveness Challenge & Lifecycle Tests ────────────────

def test_challenge_creation_returns_valid_metadata():
    """Verify /challenge generates unpredictable CSPRNG digits and 60-second TTL."""
    response = client.post("/challenge")
    assert response.status_code == 200
    data = response.json()
    assert data["challenge_id"].startswith("ch_")
    assert data["session_id"].startswith("sess_")
    assert isinstance(data["digits"], list)
    assert len(data["digits"]) == 3
    for d in data["digits"]:
        assert d.isdigit()
    assert data["expires_in_seconds"] == 60
    assert data["expires_at"] > time.time()
    assert "display" in data


def test_challenge_creation_with_json_and_session_binding():
    """Verify /challenge accepts JSON payloads and binds session_id and claimed_identity."""
    custom_session = "sess_custom_test_12345"
    response = client.post(
        "/challenge",
        json={"claimed_identity": "Zubair", "session_id": custom_session},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == custom_session
    assert data["claimed_identity"] == "Zubair"


def test_challenge_with_unregistered_claimed_identity_returns_404():
    """Verify /challenge returns 404 if a non-existent speaker is specified."""
    response = client.post(
        "/challenge",
        json={"claimed_identity": "NonExistentUserXYZ"},
    )
    assert response.status_code == 404
    assert "not registered" in response.json()["detail"].lower()


def test_verify_missing_challenge_or_session_fails_400():
    """Calling /verify without challenge_id or session_id returns 400 Bad Request."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    
    # Missing both
    resp1 = client.post(
        "/verify",
        data={"claimed_identity": "Zubair"},
        files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
    )
    assert resp1.status_code == 400
    assert "missing" in resp1.json()["detail"].lower()

    # Missing session_id
    resp2 = client.post(
        "/verify",
        data={"claimed_identity": "Zubair", "challenge_id": "ch_dummy"},
        files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
    )
    assert resp2.status_code == 400


def test_verify_unknown_challenge_id_fails_400():
    """Calling /verify with a forged or nonexistent challenge_id returns 400."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    response = client.post(
        "/verify",
        data={
            "claimed_identity": "Zubair",
            "challenge_id": "ch_nonexistent_forged_id",
            "session_id": "sess_dummy",
        },
        files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
    )
    assert response.status_code == 400
    assert "invalid or unknown challenge" in response.json()["detail"].lower()


def test_verify_reusing_consumed_challenge_fails_400():
    """A challenge can be consumed only once ('burn-on-use'). Replaying it returns 400."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    ch = client.post("/challenge", data={"claimed_identity": "Zubair"}).json()

    with patch("cloud_api.run_liveness_check", return_value=(True, "Liveness verified", "dummy")):
        with patch("cloud_api.verify_speaker", return_value={"is_accepted": True, "similarity": 0.85}):
            # First attempt: succeeds
            resp1 = client.post(
                "/verify",
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": ch["challenge_id"],
                    "session_id": ch["session_id"],
                },
                files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
            )
            assert resp1.status_code == 200

            # Second attempt: fails because challenge is already CONSUMED
            resp2 = client.post(
                "/verify",
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": ch["challenge_id"],
                    "session_id": ch["session_id"],
                },
                files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
            )
            assert resp2.status_code == 400
            assert "already been consumed" in resp2.json()["detail"].lower()


def test_verify_expired_challenge_fails_400():
    """An expired challenge (>60 seconds) must be rejected with 400."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    
    # Use controllable time via injectable time_func in a dedicated store
    fake_time = [1000.0]
    store = InMemoryChallengeStore(time_func=lambda: fake_time[0])
    ch = store.create_challenge(session_id="sess_exp", claimed_identity="Zubair", ttl_seconds=60)

    # Advance time by 61 seconds
    fake_time[0] += 61.0

    with patch("cloud_api.default_challenge_store", store):
        response = client.post(
            "/verify",
            data={
                "claimed_identity": "Zubair",
                "challenge_id": ch.challenge_id,
                "session_id": "sess_exp",
            },
            files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
        )
        assert response.status_code == 400
        assert "expired" in response.json()["detail"].lower()


def test_verify_session_mismatch_fails_400():
    """Submitting a challenge under a different session ID than it was issued for returns 400."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    ch = client.post("/challenge", data={"claimed_identity": "Zubair", "session_id": "sess_correct"}).json()

    response = client.post(
        "/verify",
        data={
            "claimed_identity": "Zubair",
            "challenge_id": ch["challenge_id"],
            "session_id": "sess_WRONG_ATTACKER",
        },
        files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
    )
    assert response.status_code == 400
    assert "session mismatch" in response.json()["detail"].lower()


def test_verify_claimed_identity_mismatch_fails_400():
    """Submitting a challenge bound to user A under user B's name returns 400."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    ch = client.post("/challenge", data={"claimed_identity": "Zubair"}).json()

    response = client.post(
        "/verify",
        data={
            "claimed_identity": "Omar",  # Claiming Omar when challenge was reserved for Zubair
            "challenge_id": ch["challenge_id"],
            "session_id": ch["session_id"],
        },
        files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
    )
    assert response.status_code == 400
    assert "bound to speaker 'zubair'" in response.json()["detail"].lower()


def test_verify_liveness_failure_prevents_inference_and_denies_access():
    """If spoken digits fail liveness, verify_speaker must NOT be called, and action must be DENY."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    ch = client.post("/challenge", data={"claimed_identity": "Zubair"}).json()

    with patch("cloud_api.run_liveness_check", return_value=(False, "Challenge failed: incorrect digits", "one two three")):
        with patch("cloud_api.verify_speaker") as mock_verify:
            response = client.post(
                "/verify",
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": ch["challenge_id"],
                    "session_id": ch["session_id"],
                },
                files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["accepted"] is False
            assert data["action"] == "DENY"
            assert data["liveness_passed"] is False
            assert "liveness check failed" in data["reason"].lower()
            mock_verify.assert_not_called()


def test_verify_transcription_failure_fails_closed():
    """If speech transcription returns None or empty, verification must fail closed."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    ch = client.post("/challenge", data={"claimed_identity": "Zubair"}).json()

    with patch("cloud_api.run_liveness_check", return_value=(False, "No speech detected. Please speak clearly.", "")):
        with patch("cloud_api.verify_speaker") as mock_verify:
            response = client.post(
                "/verify",
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": ch["challenge_id"],
                    "session_id": ch["session_id"],
                },
                files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["accepted"] is False
            assert data["action"] == "DENY"
            mock_verify.assert_not_called()


def test_verify_concurrent_consumption_race_condition_safety():
    """
    Concurrency safety test: 10 concurrent threads attempting to consume the same
    challenge ID must result in exactly 1 successful consumption and 9 rejections.
    """
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    ch = client.post("/challenge", data={"claimed_identity": "Zubair"}).json()

    results = []

    def make_attempt():
        with patch("cloud_api.run_liveness_check", return_value=(True, "Liveness verified", "dummy")):
            with patch("cloud_api.verify_speaker", return_value={"is_accepted": True, "similarity": 0.88}):
                return client.post(
                    "/verify",
                    data={
                        "claimed_identity": "Zubair",
                        "challenge_id": ch["challenge_id"],
                        "session_id": ch["session_id"],
                    },
                    files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
                )

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(make_attempt) for _ in range(10)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    status_codes = [r.status_code for r in results]
    # Exactly one request must succeed with 200, the remaining 9 must be 400
    assert status_codes.count(200) == 1, f"Expected exactly 1 200, got: {status_codes}"
    assert status_codes.count(400) == 9, f"Expected 9 400s, got: {status_codes}"


def test_verify_temp_file_cleanup_on_liveness_failure():
    """Verify temporary audio file is cleaned up when liveness check fails."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    ch = client.post("/challenge", data={"claimed_identity": "Zubair"}).json()

    created_paths = []
    import cloud_api
    original_save = cloud_api.save_upload

    def tracking_save(audio, request=None):
        path = original_save(audio, request=request)
        created_paths.append(path)
        return path

    with patch("cloud_api.save_upload", side_effect=tracking_save):
        with patch("cloud_api.run_liveness_check", return_value=(False, "Liveness failed", "")):
            resp = client.post(
                "/verify",
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": ch["challenge_id"],
                    "session_id": ch["session_id"],
                },
                files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
            )
            assert resp.status_code == 200
            assert resp.json()["accepted"] is False

    assert len(created_paths) == 1
    assert not created_paths[0].exists(), "Temporary audio file was not cleaned up after liveness failure!"


def test_in_memory_challenge_store_cleanup_expired():
    """Verify cleanup_expired method in InMemoryChallengeStore removes expired challenges."""
    fake_time = [1000.0]
    store = InMemoryChallengeStore(time_func=lambda: fake_time[0])
    ch1 = store.create_challenge(session_id="s1", ttl_seconds=30)
    ch2 = store.create_challenge(session_id="s2", ttl_seconds=120)

    # Advance time by 45 seconds (ch1 expires, ch2 remains)
    fake_time[0] += 45.0
    removed_count = store.cleanup_expired()
    assert removed_count == 1
    assert store.get_challenge(ch1.challenge_id) is None
    assert store.get_challenge(ch2.challenge_id) is not None


def test_verify_invalid_challenge_rejects_before_saving_upload():
    """Verify that calling /verify with an invalid or expired challenge rejects before saving audio upload."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    with patch("cloud_api.save_upload") as mock_save:
        response = client.post(
            "/verify",
            data={
                "claimed_identity": "Zubair",
                "challenge_id": "ch_nonexistent_test",
                "session_id": "sess_dummy",
            },
            files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
        )
        assert response.status_code == 400
        mock_save.assert_not_called()


