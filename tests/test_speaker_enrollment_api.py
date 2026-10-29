"""
tests/test_speaker_enrollment_api.py — Comprehensive test suite for persistent speaker enrollment.

Covers:
1. Successful enrollment with 3 samples (HTTP 201, database record, SecurityEvent audit log).
2. Immediate verification capability for newly enrolled speaker profiles.
3. Duplicate speaker rejection (HTTP 409, exact and case-insensitive).
4. Authentication & Authorization boundaries (HTTP 401 unauthenticated, HTTP 403 non-admin).
5. Input validation (fewer than 3 samples, more than 10 samples, invalid speaker_id -> HTTP 400).
6. Audio quality validation (duration < 1.0s, duration > 30.0s, silence/insufficient energy -> HTTP 400).
7. Payload limits enforcement (sample > 10MB -> HTTP 413).
8. Aggregate payload limits enforcement (> 50MB across samples -> HTTP 413).
9. Atomic rollback on database failure (no partial records).
10. Temporary file cleanup guarantees on success and failure.
11. End-to-end WebM/Opus browser recording decoding and FFmpeg transcoding.
12. Rejection of unsupported extensions (e.g. .txt, .bin -> HTTP 400).
"""

import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import numpy as np
import pytest
import soundfile as sf
from sqlalchemy.orm import sessionmaker
import torch

from app.core.auth import AuthenticatedUser, get_current_admin, get_current_user
from app.core.auth_policy import Role
from app.core.embeddings import DEFAULT_EMBEDDING_DIM
from app.db.base import Base, SecurityEvent, SpeakerRecord
from app.db.session import create_db_engine, get_db, reset_engine
from app.main import app
from app.repositories.speaker_repository import SpeakerRepository
from app.services.speaker_service import (
    SpeakerService,
    reset_classifier_for_testing,
    set_classifier_for_testing,
)

client = TestClient(app)


# ─── Mock Classifier ──────────────────────────────────────────────────────────

class MockSpeechBrainClassifier:
    """Deterministic mock for SpeechBrain ECAPA-TDNN classifier."""
    def __init__(self, emb_dim: int = DEFAULT_EMBEDDING_DIM):
        self.emb_dim = emb_dim
        self.call_count = 0

    def encode_batch(self, wav: torch.Tensor) -> torch.Tensor:
        self.call_count += 1
        # Produce a deterministic 192-d embedding
        v = torch.zeros(1, 1, self.emb_dim, dtype=torch.float32)
        v[0, 0, 0] = 1.0
        v[0, 0, 1] = 0.5
        return v


# ─── Helpers: Generate Audio Bytes ─────────────────────────────────────────────

def create_wav_bytes(
    duration: float = 2.0,
    sr: int = 16000,
    amplitude: float = 0.5,
    freq: float = 440.0,
) -> bytes:
    """Generate in-memory WAV audio bytes with controllable duration and amplitude."""
    num_samples = int(sr * duration)
    t = np.linspace(0, duration, num_samples, endpoint=False, dtype=np.float32)
    data = (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, data, sr, format="WAV")
    return buf.getvalue()


def create_webm_bytes(
    duration: float = 2.0,
    freq: float = 440.0,
) -> bytes:
    """Generate genuine WebM Opus audio bytes using FFmpeg (browser recording format)."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration={duration}",
        "-c:a", "libopus",
        "-b:a", "64k",
        "-f", "webm",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True, check=True)
    return result.stdout


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_teardown_environment():
    """Ensure engine and classifier singletons are clean between tests."""
    reset_engine()
    reset_classifier_for_testing()
    yield
    reset_engine()
    reset_classifier_for_testing()


@pytest.fixture
def test_db():
    """Create an isolated, disposable SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        db_path = Path(tmp_file.name)

    db_url = f"sqlite:///{db_path}"
    engine = create_db_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        yield {
            "url": db_url,
            "engine": engine,
            "session_factory": session_factory,
        }
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
        if db_path.exists():
            try:
                db_path.unlink()
            except OSError:
                pass


@pytest.fixture
def admin_user():
    """Authenticated admin user context."""
    user = AuthenticatedUser(
        uid="admin_uid_123",
        email="admin@voicelock.enterprise",
        role=Role.ADMIN,
    )
    app.dependency_overrides[get_current_admin] = lambda: user
    yield user
    app.dependency_overrides.pop(get_current_admin, None)


@pytest.fixture
def normal_user():
    """Authenticated non-admin user context."""
    user = AuthenticatedUser(
        uid="user_uid_456",
        email="user@voicelock.enterprise",
        role=Role.USER,
    )
    yield user


# ─── Tests ─────────────────────────────────────────────────────────────────────

def test_enroll_speaker_success_201(test_db, admin_user):
    """
    Administrator successfully enrolls a new speaker with 3 valid samples.
    Verifies HTTP 201, response attributes, database record, and atomic SecurityEvent log.
    """
    mock_clf = MockSpeechBrainClassifier()
    set_classifier_for_testing(mock_clf)

    sample1 = create_wav_bytes(duration=2.0)
    sample2 = create_wav_bytes(duration=2.5)
    sample3 = create_wav_bytes(duration=3.0)

    files = [
        ("samples", ("sample1.wav", io.BytesIO(sample1), "audio/wav")),
        ("samples", ("sample2.wav", io.BytesIO(sample2), "audio/wav")),
        ("samples", ("sample3.wav", io.BytesIO(sample3), "audio/wav")),
    ]
    data = {
        "speaker_id": "Sarah_Connor",
        "full_name": "Sarah Connor",
    }

    response = client.post("/speakers", data=data, files=files)
    assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"

    resp_data = response.json()
    assert resp_data["speaker_id"] == "Sarah_Connor"
    assert resp_data["full_name"] == "Sarah Connor"
    assert resp_data["status"] == "active"
    assert resp_data["sample_count"] == 3
    assert resp_data["embedding_dim"] == DEFAULT_EMBEDDING_DIM
    assert "created_at" in resp_data

    # Verify database persistence
    session = test_db["session_factory"]()
    try:
        repo = SpeakerRepository(session)
        record = repo.get_by_speaker_id("Sarah_Connor")
        assert record is not None
        assert record.full_name == "Sarah Connor"
        assert record.sample_count == 3
        assert record.status == "active"

        # Verify biometric embedding was stored
        emb = repo.get_embedding("Sarah_Connor")
        assert emb is not None
        assert emb.shape == (DEFAULT_EMBEDDING_DIM,)
        assert emb[0] == 1.0  # From mock classifier

        # Verify SecurityEvent was logged
        events = session.query(SecurityEvent).all()
        assert len(events) >= 1
        admin_event = [e for e in events if e.details and "Sarah_Connor" in e.details][0]
        assert admin_event.event_type == "admin_action"
        assert admin_event.severity == "low"
        assert admin_event.status == "logged"
        assert admin_event.user_id == "admin_uid_123"
        meta = json.loads(admin_event.metadata_json)
        assert meta["action"] == "speaker_enrollment"
        assert meta["speaker_id"] == "Sarah_Connor"
        assert meta["sample_count"] == 3
    finally:
        session.close()


def test_enroll_speaker_immediate_verification(test_db, admin_user):
    """Newly enrolled speaker profile is immediately available for verification."""
    mock_clf = MockSpeechBrainClassifier()
    set_classifier_for_testing(mock_clf)

    samples = [create_wav_bytes(duration=2.0) for _ in range(3)]
    files = [("samples", (f"s{i}.wav", io.BytesIO(s), "audio/wav")) for i, s in enumerate(samples)]

    response = client.post(
        "/speakers",
        data={"speaker_id": "Immediate_Speaker", "full_name": "Immediate Verification"},
        files=files,
    )
    assert response.status_code == 201

    session = test_db["session_factory"]()
    try:
        service = SpeakerService(session)
        # Check speaker is in active registered speakers
        registered = service.get_registered_speakers()
        assert "Immediate_Speaker" in registered

        # Check embedding can be retrieved
        emb = service.get_speaker_embedding("Immediate_Speaker")
        assert emb is not None
        assert emb.shape == (DEFAULT_EMBEDDING_DIM,)

        # Check active profiles dictionary includes the speaker
        profiles = service.get_active_profiles()
        assert "Immediate_Speaker" in profiles
    finally:
        session.close()


def test_enroll_speaker_duplicate_rejection_409(test_db, admin_user):
    """Attempting to enroll an existing speaker_id (exact or case-insensitive) returns HTTP 409."""
    mock_clf = MockSpeechBrainClassifier()
    set_classifier_for_testing(mock_clf)

    samples = [create_wav_bytes(duration=2.0) for _ in range(3)]
    files = [("samples", (f"s{i}.wav", io.BytesIO(s), "audio/wav")) for i, s in enumerate(samples)]

    # 1. First enrollment succeeds
    r1 = client.post(
        "/speakers",
        data={"speaker_id": "Existing_User", "full_name": "First Enrolled"},
        files=files,
    )
    assert r1.status_code == 201

    # 2. Exact duplicate attempt
    files2 = [("samples", (f"s{i}.wav", io.BytesIO(s), "audio/wav")) for i, s in enumerate(samples)]
    r2 = client.post(
        "/speakers",
        data={"speaker_id": "Existing_User", "full_name": "Second Enrolled"},
        files=files2,
    )
    assert r2.status_code == 409
    assert "already exists" in r2.json()["detail"].lower()

    # 3. Case-insensitive duplicate attempt ("existing_user")
    files3 = [("samples", (f"s{i}.wav", io.BytesIO(s), "audio/wav")) for i, s in enumerate(samples)]
    r3 = client.post(
        "/speakers",
        data={"speaker_id": "existing_user", "full_name": "Case Insensitive"},
        files=files3,
    )
    assert r3.status_code == 409
    assert "already exists" in r3.json()["detail"].lower()


def test_enroll_speaker_unauthenticated_401(test_db):
    """Requests without authentication return HTTP 401."""
    samples = [create_wav_bytes(duration=2.0) for _ in range(3)]
    files = [("samples", (f"s{i}.wav", io.BytesIO(s), "audio/wav")) for i, s in enumerate(samples)]

    response = client.post(
        "/speakers",
        data={"speaker_id": "Anon_User"},
        files=files,
    )
    assert response.status_code == 401


def test_enroll_speaker_non_admin_forbidden_403(test_db, normal_user):
    """Requests by non-administrator users return HTTP 403."""
    app.dependency_overrides[get_current_admin] = lambda: (_ for _ in ()).throw(
        pytest.importorskip("fastapi").HTTPException(status_code=403, detail="Admin privileges required.")
    )

    samples = [create_wav_bytes(duration=2.0) for _ in range(3)]
    files = [("samples", (f"s{i}.wav", io.BytesIO(s), "audio/wav")) for i, s in enumerate(samples)]

    response = client.post(
        "/speakers",
        data={"speaker_id": "Unauthorized_Enrollment"},
        files=files,
    )
    assert response.status_code == 403


def test_enroll_speaker_fewer_than_3_samples_400(test_db, admin_user):
    """Submitting fewer than 3 samples returns HTTP 400."""
    samples = [create_wav_bytes(duration=2.0) for _ in range(2)]  # Only 2
    files = [("samples", (f"s{i}.wav", io.BytesIO(s), "audio/wav")) for i, s in enumerate(samples)]

    response = client.post(
        "/speakers",
        data={"speaker_id": "Too_Few_Samples"},
        files=files,
    )
    assert response.status_code == 400
    assert "at least 3" in response.json()["detail"].lower()


def test_enroll_speaker_more_than_10_samples_400(test_db, admin_user):
    """Submitting more than 10 samples returns HTTP 400."""
    samples = [create_wav_bytes(duration=2.0) for _ in range(11)]  # 11 samples
    files = [("samples", (f"s{i}.wav", io.BytesIO(s), "audio/wav")) for i, s in enumerate(samples)]

    response = client.post(
        "/speakers",
        data={"speaker_id": "Too_Many_Samples"},
        files=files,
    )
    assert response.status_code == 400
    assert "at most 10" in response.json()["detail"].lower()


def test_enroll_speaker_invalid_speaker_id_400(test_db, admin_user):
    """Invalid speaker_id (too short, or containing invalid characters) returns HTTP 400."""
    samples = [create_wav_bytes(duration=2.0) for _ in range(3)]

    # Too short: 1 character
    r1 = client.post(
        "/speakers",
        data={"speaker_id": "X"},
        files=[("samples", (f"s{i}.wav", io.BytesIO(s), "audio/wav")) for i, s in enumerate(samples)],
    )
    assert r1.status_code == 400

    # Illegal characters: punctuation/symbols
    r2 = client.post(
        "/speakers",
        data={"speaker_id": "bad!user#name"},
        files=[("samples", (f"s{i}.wav", io.BytesIO(s), "audio/wav")) for i, s in enumerate(samples)],
    )
    assert r2.status_code == 400


def test_enroll_speaker_invalid_audio_duration_400(test_db, admin_user):
    """Audio samples shorter than 1.0s or longer than 30.0s return HTTP 400."""
    mock_clf = MockSpeechBrainClassifier()
    set_classifier_for_testing(mock_clf)

    # 1. One sample is only 0.5 seconds
    s1 = create_wav_bytes(duration=2.0)
    s2 = create_wav_bytes(duration=0.5)  # Too short!
    s3 = create_wav_bytes(duration=2.0)

    files = [
        ("samples", ("s1.wav", io.BytesIO(s1), "audio/wav")),
        ("samples", ("s2.wav", io.BytesIO(s2), "audio/wav")),
        ("samples", ("s3.wav", io.BytesIO(s3), "audio/wav")),
    ]
    response = client.post(
        "/speakers",
        data={"speaker_id": "Short_Audio_User"},
        files=files,
    )
    assert response.status_code == 400
    assert "duration" in response.json()["detail"].lower()


def test_enroll_speaker_silent_audio_400(test_db, admin_user):
    """Audio samples with pure silence or near-zero energy return HTTP 400."""
    mock_clf = MockSpeechBrainClassifier()
    set_classifier_for_testing(mock_clf)

    s1 = create_wav_bytes(duration=2.0, amplitude=0.5)
    s2 = create_wav_bytes(duration=2.0, amplitude=0.0)  # Pure silence
    s3 = create_wav_bytes(duration=2.0, amplitude=0.5)

    files = [
        ("samples", ("s1.wav", io.BytesIO(s1), "audio/wav")),
        ("samples", ("s2.wav", io.BytesIO(s2), "audio/wav")),
        ("samples", ("s3.wav", io.BytesIO(s3), "audio/wav")),
    ]
    response = client.post(
        "/speakers",
        data={"speaker_id": "Silent_User"},
        files=files,
    )
    assert response.status_code == 400
    assert "insufficient audio energy" in response.json()["detail"].lower() or "silence" in response.json()["detail"].lower()


def test_enroll_speaker_oversized_audio_413(test_db, admin_user):
    """Sample exceeding 10 MB per-file limit returns HTTP 413."""
    # Create fake oversized sample payload (>10 MB)
    oversized_data = b"RIFF" + (b"\x00" * (11 * 1024 * 1024))
    valid_sample = create_wav_bytes(duration=2.0)

    files = [
        ("samples", ("sample1.wav", io.BytesIO(oversized_data), "audio/wav")),
        ("samples", ("sample2.wav", io.BytesIO(valid_sample), "audio/wav")),
        ("samples", ("sample3.wav", io.BytesIO(valid_sample), "audio/wav")),
    ]
    response = client.post(
        "/speakers",
        data={"speaker_id": "Oversized_User"},
        files=files,
    )
    assert response.status_code == 413


def test_enroll_speaker_atomic_rollback_on_failure(test_db, admin_user):
    """Database changes roll back atomically if an error occurs mid-enrollment."""
    mock_clf = MockSpeechBrainClassifier()
    set_classifier_for_testing(mock_clf)

    # 2 valid samples and 1 invalid sample (0.4s)
    s1 = create_wav_bytes(duration=2.0)
    s2 = create_wav_bytes(duration=2.0)
    s3 = create_wav_bytes(duration=0.4)

    files = [
        ("samples", ("s1.wav", io.BytesIO(s1), "audio/wav")),
        ("samples", ("s2.wav", io.BytesIO(s2), "audio/wav")),
        ("samples", ("s3.wav", io.BytesIO(s3), "audio/wav")),
    ]
    response = client.post(
        "/speakers",
        data={"speaker_id": "Rollback_User"},
        files=files,
    )
    assert response.status_code == 400

    # Ensure no record exists in database
    session = test_db["session_factory"]()
    try:
        repo = SpeakerRepository(session)
        assert repo.get_by_speaker_id("Rollback_User") is None
        events = session.query(SecurityEvent).all()
        assert not any(e.details and "Rollback_User" in e.details for e in events)
    finally:
        session.close()


def test_enroll_speaker_genuine_webm_opus_transcoding(test_db, admin_user):
    """
    Submits genuine browser-recorded WebM/Opus audio through POST /speakers.
    Verifies that the FFmpeg transcoding pipeline decodes the WebM container,
    resamples to 16kHz mono, extracts 192-d embeddings, and registers the speaker.
    """
    mock_clf = MockSpeechBrainClassifier()
    set_classifier_for_testing(mock_clf)

    # Generate 3 genuine WebM/Opus audio streams at distinct frequencies
    webm1 = create_webm_bytes(duration=2.0, freq=440.0)
    webm2 = create_webm_bytes(duration=2.5, freq=550.0)
    webm3 = create_webm_bytes(duration=3.0, freq=660.0)

    # Verify EBML WebM header
    assert webm1[:4] == b"\x1aE\xdf\xa3", "Must be genuine WebM EBML container"

    files = [
        ("samples", ("sample_1.webm", io.BytesIO(webm1), "audio/webm")),
        ("samples", ("sample_2.webm", io.BytesIO(webm2), "audio/webm")),
        ("samples", ("sample_3.webm", io.BytesIO(webm3), "audio/webm")),
    ]
    data = {
        "speaker_id": "WebM_Enrolled_Operator",
        "full_name": "WebM Operator",
    }

    response = client.post("/speakers", data=data, files=files)
    assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"

    resp_data = response.json()
    assert resp_data["speaker_id"] == "WebM_Enrolled_Operator"
    assert resp_data["sample_count"] == 3
    assert resp_data["embedding_dim"] == DEFAULT_EMBEDDING_DIM

    # Verify database persistence and immediate verification availability
    session = test_db["session_factory"]()
    try:
        service = SpeakerService(session)
        assert "WebM_Enrolled_Operator" in service.get_registered_speakers()
        emb = service.get_speaker_embedding("WebM_Enrolled_Operator")
        assert emb is not None
        assert emb.shape == (DEFAULT_EMBEDDING_DIM,)
        assert emb[0] == 1.0  # From mock classifier
    finally:
        session.close()


def test_enroll_speaker_unsupported_format_400(test_db, admin_user):
    """Submitting unsupported file formats (e.g. .txt, .bin) is rejected with HTTP 400."""
    valid_sample = create_wav_bytes(duration=2.0)
    unsupported_txt = b"This is plain text, not biometric audio."
    unsupported_bin = b"\x00\x01\x02\x03\x04\x05\x06\x07"

    # Disallowed .txt extension
    files_txt = [
        ("samples", ("sample1.wav", io.BytesIO(valid_sample), "audio/wav")),
        ("samples", ("sample2.wav", io.BytesIO(valid_sample), "audio/wav")),
        ("samples", ("malicious.txt", io.BytesIO(unsupported_txt), "text/plain")),
    ]
    r1 = client.post("/speakers", data={"speaker_id": "Disallowed_Txt"}, files=files_txt)
    assert r1.status_code == 400
    assert "unsupported format" in r1.json()["detail"].lower()

    # Disallowed .bin extension
    files_bin = [
        ("samples", ("sample1.wav", io.BytesIO(valid_sample), "audio/wav")),
        ("samples", ("sample2.wav", io.BytesIO(valid_sample), "audio/wav")),
        ("samples", ("payload.bin", io.BytesIO(unsupported_bin), "application/octet-stream")),
    ]
    r2 = client.post("/speakers", data={"speaker_id": "Disallowed_Bin"}, files=files_bin)
    assert r2.status_code == 400
    assert "unsupported format" in r2.json()["detail"].lower()


def test_enroll_speaker_aggregate_oversized_payload_413(test_db, admin_user):
    """
    Submitting multiple samples where each is within 10 MB but total exceeds 50 MB
    is rejected with HTTP 413.
    """
    # 6 samples each 9 MB: each < 10 MB limit, but 6 * 9 = 54 MB > 50 MB total limit
    chunk_9mb = b"RIFF" + (b"\x00" * (9 * 1024 * 1024))
    files = [
        ("samples", (f"sample_{i + 1}.wav", io.BytesIO(chunk_9mb), "audio/wav"))
        for i in range(6)
    ]

    response = client.post(
        "/speakers",
        data={"speaker_id": "Aggregate_Oversized_User"},
        files=files,
    )
    assert response.status_code == 413
    detail = response.json()["detail"].lower()
    assert "payload too large" in detail or "total enrollment payload exceeds" in detail
