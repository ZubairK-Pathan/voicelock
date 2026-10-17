"""
tests/test_api.py — Automated test suite for VoiceLock FastAPI endpoints.

Covers:
- Basic health and discovery (GET /, GET /speakers)
- Input validation (missing audio, empty audio, invalid formats, oversized uploads)
- Security controls (server-side threshold enforcement, safe error messages)
- ML inference error handling and temp-file lifecycle
- Integration with real/mocked model pipeline
"""

import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from cloud_api import app, MAX_AUDIO_SIZE_BYTES, SERVER_THRESHOLD

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


# ─── Input Hardening & Error Handling Tests ───────────────────────────────────

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


def test_oversized_audio_rejected():
    """Sending an audio payload exceeding MAX_AUDIO_SIZE_BYTES must return 413 Payload Too Large."""
    oversized_data = b"0" * (MAX_AUDIO_SIZE_BYTES + 1024)
    response = client.post(
        "/identify",
        files={"audio": ("huge.wav", io.BytesIO(oversized_data), "audio/wav")},
    )
    assert response.status_code == 413
    assert "exceeds" in response.json()["detail"].lower()


def test_client_cannot_override_server_threshold():
    """
    Security check: Client attempting to submit threshold=0.01 must not override
    the server-enforced threshold.
    """
    # Create valid dummy WAV
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    
    mock_result = {
        "is_accepted": False,
        "similarity": 0.15,
        "threshold": SERVER_THRESHOLD,
        "claimed_identity": "Zubair",
    }
    with patch("cloud_api.verify_speaker", return_value=mock_result) as mock_verify:
        response = client.post(
            "/verify",
            data={"claimed_identity": "Zubair", "threshold": 0.01},  # Attempting to override
            files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
        )
        assert response.status_code == 200
        # The API must use SERVER_THRESHOLD, not the client's 0.01
        assert response.json()["threshold_used"] == SERVER_THRESHOLD
        mock_verify.assert_called_once()
        # Verify the call passed SERVER_THRESHOLD
        _, kwargs = mock_verify.call_args
        assert kwargs.get("threshold") == SERVER_THRESHOLD


def test_inference_failure_returns_safe_500():
    """Inference exception must return 500 without leaking stack traces or internal filesystem paths."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    
    with patch("cloud_api.predict_speaker", side_effect=RuntimeError("internal CUDA/CPU execution error")):
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
    """If profiles dictionary is empty, API returns 503 or 400 without crashing."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    
    with patch("cloud_api.get_system", return_value=({}, MagicMock())):
        response = client.post(
            "/identify",
            files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
        )
        assert response.status_code in [400, 503]
        assert "no speaker profiles" in response.json()["detail"].lower()


def test_temp_file_cleanup_on_success_and_failure():
    """Verify temporary audio files are removed from disk on both successful and failed inference."""
    dummy_wav = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    
    created_temp_files = []
    original_save = cloud_api_save_upload = None

    import cloud_api
    original_save = cloud_api.save_upload

    def tracking_save(audio):
        path = original_save(audio)
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
        with patch("cloud_api.predict_speaker", side_effect=RuntimeError("boom")):
            resp = client.post(
                "/identify",
                files={"audio": ("test.wav", io.BytesIO(dummy_wav), "audio/wav")},
            )
            assert resp.status_code == 500

    # Verify all tracked temporary files were unlinked
    assert len(created_temp_files) == 2
    for tmp in created_temp_files:
        assert not tmp.exists(), f"Temporary file {tmp} was not cleaned up!"
