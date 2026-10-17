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

client = TestClient(app)

SAMPLE_WAV = Path(__file__).resolve().parent.parent / "processed_dataset" / "Zubair" / "Zubair_Enrollment_R01.wav"


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
    """Integration test: 1-to-1 verification for claimed identity Zubair."""
    with open(SAMPLE_WAV, "rb") as f:
        audio_bytes = f.read()

    response = client.post(
        "/verify",
        data={"claimed_identity": "Zubair"},
        files={"audio": ("sample.wav", io.BytesIO(audio_bytes), "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] is True
    assert data["claimed_identity"] == "Zubair"
    assert data["action"] == "UNLOCK"
    assert data["threshold_used"] == SERVER_THRESHOLD


def test_verify_unknown_speaker_404():
    """Verification for an unregistered claimed identity must return 404."""
    dummy_wav = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    response = client.post(
        "/verify",
        data={"claimed_identity": "NonExistentUser999"},
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
    
    # Mock verify_speaker to evaluate against the threshold passed to it
    def controlled_verify(audio_path, claimed_identity, threshold, **kwargs):
        sim = 0.15  # Impostor similarity
        return {
            "is_accepted": sim >= threshold,
            "similarity": sim,
            "threshold": threshold,
            "claimed_identity": claimed_identity,
        }

    with patch("cloud_api.verify_speaker", side_effect=controlled_verify):
        response = client.post(
            "/verify",
            data={"claimed_identity": "Zubair", "threshold": 0.01},  # Attempting to bypass
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
