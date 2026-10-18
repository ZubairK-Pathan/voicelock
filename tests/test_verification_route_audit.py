"""
tests/test_verification_route_audit.py — Comprehensive test suite for verification outcome persistence.

Increment 3C.3: Persist Verification Outcomes.

Covers:
1. Successful verification records exactly one 'verified' event with correct identity mapping.
2. Biometric rejection records exactly one 'rejected' event.
3. Challenge failure (spoken liveness failure) records exactly one 'challenge_failed' event.
4. Device verification records 'device' verification_flow and device_id.
5. Processing failures (audio decoding, conversion, inference) record 'error' events.
6. Authentication failures (401) do not record verification events.
7. Authorization failures (403 cross-user) do not record verification events.
8. Pre-attempt rejections (missing/expired challenge, missing speaker, bad request) do not record events.
9. Verified outcome database commit failure fails closed (HTTP 500) and does not unlock.
10. Rejected outcome database commit failure preserves the denial HTTP response.
11. Correlation identifier (X-Request-ID / X-Correlation-ID) propagation and sanitization.
12. Zero sensitive data (audio, paths, embeddings, scores, credentials) persisted in verification events.
13. Exactly-once / at-most-once attempt recording guarantee.
"""

import io
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import numpy as np
import pytest
import soundfile as sf
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.core.auth import AuthenticatedUser
from app.core.auth_policy import Role
from app.core.config import SERVER_THRESHOLD
from app.core.device_auth import AuthenticatedDevice, get_current_actor
from app.core.embeddings import DEFAULT_EMBEDDING_DIM
from app.core.rate_limit import _challenge_limiter, _identify_limiter, _verify_limiter
from app.db.base import Base, VerificationEvent
from app.db.session import create_db_engine, get_db, reset_engine
from app.main import app
from app.repositories.speaker_repository import SpeakerRepository
from app.repositories.user_speaker_repository import UserSpeakerRepository
from app.services.challenge_service import get_challenge_store
from app.services.speaker_service import reset_classifier_for_testing

client = TestClient(app)

DUMMY_WAV_BYTES = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_test_environment():
    """Reset singletons, rate limiters, and engines before and after each test."""
    reset_engine()
    reset_classifier_for_testing()
    _challenge_limiter.reset_for_testing()
    _verify_limiter.reset_for_testing()
    _identify_limiter.reset_for_testing()
    yield
    reset_engine()
    reset_classifier_for_testing()
    _challenge_limiter.reset_for_testing()
    _verify_limiter.reset_for_testing()
    _identify_limiter.reset_for_testing()


@pytest.fixture
def test_db():
    """Create an isolated, disposable SQLite database for route audit tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        db_path = Path(tmp_file.name)

    db_url = f"sqlite:///{db_path}"
    engine = create_db_engine(db_url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    try:
        yield {"url": db_url, "engine": engine, "session_factory": session_factory}
    finally:
        engine.dispose()
        if db_path.exists():
            try:
                db_path.unlink()
            except OSError:
                pass


@pytest.fixture
def enrolled_speakers(test_db):
    """
    Populate database with synthetic enrolled speakers and user mappings:
    - Alice: Active speaker mapped to 'uid-alice-123'
    - Bob: Active speaker (orthogonal vector) mapped to 'uid-bob-456'
    """
    rng = np.random.RandomState(42)

    vec_alice = rng.randn(DEFAULT_EMBEDDING_DIM).astype(np.float32)
    vec_alice /= np.linalg.norm(vec_alice)

    vec_bob = rng.randn(DEFAULT_EMBEDDING_DIM).astype(np.float32)
    vec_bob -= np.dot(vec_bob, vec_alice) * vec_alice
    vec_bob /= np.linalg.norm(vec_bob)

    with test_db["session_factory"]() as session:
        speaker_repo = SpeakerRepository(session)
        user_speaker_repo = UserSpeakerRepository(session)

        speaker_repo.create(
            speaker_id="Alice",
            full_name="Alice Lead",
            status="active",
            embedding=vec_alice,
        )
        user_speaker_repo.create(
            firebase_uid="uid-alice-123",
            speaker_id="Alice",
            assigned_by="system",
        )

        speaker_repo.create(
            speaker_id="Bob",
            full_name="Bob Operator",
            status="active",
            embedding=vec_bob,
        )
        user_speaker_repo.create(
            firebase_uid="uid-bob-456",
            speaker_id="Bob",
            assigned_by="system",
        )

        session.commit()

    return {
        "alice_vec": vec_alice,
        "bob_vec": vec_bob,
    }


# ─── Helper Functions ──────────────────────────────────────────────────────────

def _create_challenge(claimed_identity="Alice", session_id="sess-audit-01"):
    """Helper to generate a valid liveness challenge for testing."""
    store = get_challenge_store()
    return store.create_challenge(
        session_id=session_id,
        claimed_identity=claimed_identity,
        ttl_seconds=60,
    )


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_successful_verification_records_single_verified_event(test_db, enrolled_speakers):
    """
    1. Successful verification:
       - liveness passes, biometric similarity exceeds threshold.
       - Returns 200 with accepted=True, action='UNLOCK'.
       - Persists exactly one event with outcome='verified', flow='web', user_id, speaker_id, request_id.
    """
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db():
        session = test_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db

    try:
        ch = _create_challenge(claimed_identity="Alice", session_id="sess-001")

        with patch("app.api.routes_verification._get_run_liveness_check", return_value=lambda p, d: (True, "Digits matched", "123")):
            with patch("app.api.routes_verification._get_verify_speaker", return_value=lambda **kw: {"is_accepted": True, "similarity": 0.88}):
                response = client.post(
                    "/verify",
                    data={
                        "claimed_identity": "Alice",
                        "challenge_id": ch.challenge_id,
                        "session_id": "sess-001",
                    },
                    headers={"X-Request-ID": "req-verified-test-001"},
                    files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] is True
        assert data["action"] == "UNLOCK"

        # Verify database record
        with test_db["session_factory"]() as session:
            events = session.scalars(select(VerificationEvent)).all()
            assert len(events) == 1
            event = events[0]
            assert event.outcome == "verified"
            assert event.verification_flow == "web"
            assert event.user_id == "uid-alice-123"
            assert event.speaker_id == "Alice"
            assert event.device_id is None
            assert event.request_id == "req-verified-test-001"
            assert event.created_at is not None
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_biometric_rejection_records_single_rejected_event(test_db, enrolled_speakers):
    """
    2. Biometric rejection:
       - liveness passes, but biometric decision rejects the speaker.
       - Returns 200 with accepted=False, action='DENY'.
       - Persists exactly one event with outcome='rejected'.
    """
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db():
        session = test_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db

    try:
        ch = _create_challenge(claimed_identity="Alice", session_id="sess-002")

        with patch("app.api.routes_verification._get_run_liveness_check", return_value=lambda p, d: (True, "Digits matched", "123")):
            with patch("app.api.routes_verification._get_verify_speaker", return_value=lambda **kw: {"is_accepted": False, "similarity": 0.12}):
                response = client.post(
                    "/verify",
                    data={
                        "claimed_identity": "Alice",
                        "challenge_id": ch.challenge_id,
                        "session_id": "sess-002",
                    },
                    headers={"X-Correlation-ID": "corr-rejected-002"},
                    files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] is False
        assert data["action"] == "DENY"

        with test_db["session_factory"]() as session:
            events = session.scalars(select(VerificationEvent)).all()
            assert len(events) == 1
            event = events[0]
            assert event.outcome == "rejected"
            assert event.verification_flow == "web"
            assert event.user_id == "uid-alice-123"
            assert event.speaker_id == "Alice"
            assert event.device_id is None
            assert event.request_id == "corr-rejected-002"
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_challenge_failure_records_single_challenge_failed_event(test_db, enrolled_speakers):
    """
    3. Spoken liveness check fails:
       - liveness fails closed without running biometric inference.
       - Returns 200 with accepted=False, action='DENY', liveness_passed=False.
       - Persists exactly one event with outcome='challenge_failed'.
    """
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db():
        session = test_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db

    try:
        ch = _create_challenge(claimed_identity="Alice", session_id="sess-003")

        with patch("app.api.routes_verification._get_run_liveness_check", return_value=lambda p, d: (False, "Spoofing or digits mismatch", "999")):
            with patch("app.api.routes_verification._get_verify_speaker") as mock_verify:
                response = client.post(
                    "/verify",
                    data={
                        "claimed_identity": "Alice",
                        "challenge_id": ch.challenge_id,
                        "session_id": "sess-003",
                    },
                    files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] is False
        assert data["action"] == "DENY"
        assert data["liveness_passed"] is False
        mock_verify.assert_not_called()

        with test_db["session_factory"]() as session:
            events = session.scalars(select(VerificationEvent)).all()
            assert len(events) == 1
            event = events[0]
            assert event.outcome == "challenge_failed"
            assert event.speaker_id == "Alice"
            assert event.user_id == "uid-alice-123"
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_device_verification_records_device_flow_and_device_id(test_db, enrolled_speakers):
    """
    4. Authenticated device verification:
       - Caller is AuthenticatedDevice.
       - Verification succeeds.
       - Persists event with verification_flow='device', device_id, and user_id=None.
    """
    device_actor = AuthenticatedDevice(
        device_id="turnstile-gate-01",
        name="Main Gate Turnstile",
        auth_scheme="hmac_sha256",
    )

    def override_db():
        session = test_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: device_actor
    app.dependency_overrides[get_db] = override_db

    try:
        ch = _create_challenge(claimed_identity="Alice", session_id="sess-dev-01")

        with patch("app.api.routes_verification._get_run_liveness_check", return_value=lambda p, d: (True, "Passed", "123")):
            with patch("app.api.routes_verification._get_verify_speaker", return_value=lambda **kw: {"is_accepted": True, "similarity": 0.88}):
                response = client.post(
                    "/verify",
                    data={
                        "claimed_identity": "Alice",
                        "challenge_id": ch.challenge_id,
                        "session_id": "sess-dev-01",
                    },
                    files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                )

        assert response.status_code == 200
        assert response.json()["accepted"] is True

        with test_db["session_factory"]() as session:
            events = session.scalars(select(VerificationEvent)).all()
            assert len(events) == 1
            event = events[0]
            assert event.outcome == "verified"
            assert event.verification_flow == "device"
            assert event.device_id == "turnstile-gate-01"
            assert event.user_id is None
            assert event.speaker_id == "Alice"
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_processing_failure_audio_decoding_records_error_event(test_db, enrolled_speakers):
    """
    5. Audio decoding failure during processing:
       - Challenge is consumed.
       - Reading audio raises sf.LibsndfileError / ValueError.
       - Returns HTTP 400.
       - Persists exactly one event with outcome='error'.
    """
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db():
        session = test_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db

    try:
        ch = _create_challenge(claimed_identity="Alice", session_id="sess-err-01")

        def mock_liveness_fail_reading(path, digits):
            raise sf.LibsndfileError(1, "Format not recognised.")

        with patch("app.api.routes_verification._get_run_liveness_check", return_value=mock_liveness_fail_reading):
            response = client.post(
                "/verify",
                data={
                    "claimed_identity": "Alice",
                    "challenge_id": ch.challenge_id,
                    "session_id": "sess-err-01",
                },
                files={"audio": ("corrupted.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
            )

        assert response.status_code == 400
        assert "unreadable audio" in response.json()["detail"].lower()

        with test_db["session_factory"]() as session:
            events = session.scalars(select(VerificationEvent)).all()
            assert len(events) == 1
            assert events[0].outcome == "error"
            assert events[0].speaker_id == "Alice"
            assert events[0].user_id == "uid-alice-123"
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_processing_failure_inference_exception_records_error_event(test_db, enrolled_speakers):
    """
    6. Biometric inference runtime failure:
       - Challenge is consumed and liveness passes.
       - ML inference raises Exception.
       - Returns HTTP 500.
       - Persists exactly one event with outcome='error'.
    """
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db():
        session = test_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db

    try:
        ch = _create_challenge(claimed_identity="Alice", session_id="sess-err-02")

        def failing_verify(**kw):
            raise RuntimeError("ECAPA-TDNN inference tensor failure")

        with patch("app.api.routes_verification._get_run_liveness_check", return_value=lambda p, d: (True, "Passed", "123")):
            with patch("app.api.routes_verification._get_verify_speaker", return_value=failing_verify):
                response = client.post(
                    "/verify",
                    data={
                        "claimed_identity": "Alice",
                        "challenge_id": ch.challenge_id,
                        "session_id": "sess-err-02",
                    },
                    files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                )

        assert response.status_code == 500
        assert "inference failed" in response.json()["detail"].lower()

        with test_db["session_factory"]() as session:
            events = session.scalars(select(VerificationEvent)).all()
            assert len(events) == 1
            assert events[0].outcome == "error"
            assert events[0].speaker_id == "Alice"
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_authentication_failures_do_not_record_verification_events(test_db):
    """
    7. Authentication failure:
       - Request lacks valid bearer token or device credentials.
       - Returns HTTP 401.
       - Zero events recorded.
    """
    def override_db():
        session = test_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db

    try:
        response = client.post(
            "/verify",
            data={
                "claimed_identity": "Alice",
                "challenge_id": "fake-ch-1",
                "session_id": "fake-sess-1",
            },
            files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
        )
        assert response.status_code == 401

        with test_db["session_factory"]() as session:
            events = session.scalars(select(VerificationEvent)).all()
            assert len(events) == 0
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_authorization_failures_do_not_record_verification_events(test_db, enrolled_speakers):
    """
    8. User-speaker authorization failure:
       - User Bob attempts to verify speaker Alice (cross-speaker verification prohibited).
       - Returns HTTP 403 Forbidden.
       - Zero verification events recorded (does not falsely record biometric rejection).
    """
    bob_user = AuthenticatedUser(
        uid="uid-bob-456",
        email="bob@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db():
        session = test_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: bob_user
    app.dependency_overrides[get_db] = override_db

    try:
        ch = _create_challenge(claimed_identity="Alice", session_id="sess-auth-01")

        response = client.post(
            "/verify",
            data={
                "claimed_identity": "Alice",
                "challenge_id": ch.challenge_id,
                "session_id": "sess-auth-01",
            },
            files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
        )
        assert response.status_code == 403

        with test_db["session_factory"]() as session:
            events = session.scalars(select(VerificationEvent)).all()
            assert len(events) == 0
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_pre_attempt_rejections_do_not_record_events(test_db, enrolled_speakers):
    """
    9. Pre-attempt rejections:
       - Missing challenge_id / session_id (400)
       - Invalid or expired challenge (400)
       - Nonexistent speaker (404)
       - None of these valid pre-attempt rejections create verification events.
    """
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db():
        session = test_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db

    try:
        # A. Missing challenge_id
        r1 = client.post(
            "/verify",
            data={"claimed_identity": "Alice"},
            files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
        )
        assert r1.status_code == 400

        # B. Forged challenge_id
        r2 = client.post(
            "/verify",
            data={
                "claimed_identity": "Alice",
                "challenge_id": "forged-ch-999",
                "session_id": "sess-01",
            },
            files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
        )
        assert r2.status_code == 400

        # C. Nonexistent speaker
        r3 = client.post(
            "/verify",
            data={
                "claimed_identity": "NonexistentUser",
                "challenge_id": "ch-01",
                "session_id": "sess-01",
            },
            files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
        )
        assert r3.status_code == 404

        with test_db["session_factory"]() as session:
            events = session.scalars(select(VerificationEvent)).all()
            assert len(events) == 0
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_verified_database_failure_fails_closed_with_http_500(test_db, enrolled_speakers):
    """
    10. Transaction failure policy for VERIFIED:
        - Biometric match is accepted, but db.commit fails during event audit logging.
        - Fails closed: raises HTTP 500, rollback session, and does NOT return UNLOCK.
    """
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db_failing_commit():
        session = test_db["session_factory"]()
        orig_commit = session.commit

        def failing_commit():
            raise OperationalError("disk I/O error during commit", None, None)

        session.commit = failing_commit
        try:
            yield session
        finally:
            session.commit = orig_commit
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db_failing_commit

    try:
        ch = _create_challenge(claimed_identity="Alice", session_id="sess-db-fail-01")

        with patch("app.api.routes_verification._get_run_liveness_check", return_value=lambda p, d: (True, "Passed", "123")):
            with patch("app.api.routes_verification._get_verify_speaker", return_value=lambda **kw: {"is_accepted": True, "similarity": 0.88}):
                response = client.post(
                    "/verify",
                    data={
                        "claimed_identity": "Alice",
                        "challenge_id": ch.challenge_id,
                        "session_id": "sess-db-fail-01",
                    },
                    files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                )

        # Non-repudiation failure: fail closed with 500
        assert response.status_code == 500
        assert "database failure recording verification audit trail" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_rejected_database_failure_returns_denial_and_does_not_mask_rejection(test_db, enrolled_speakers):
    """
    11. Transaction failure policy for REJECTED:
        - Biometric match rejected (similarity < threshold).
        - db.commit fails during audit persistence.
        - Rolls back and still returns 200 with action='DENY' without crashing or masking rejection.
    """
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db_failing_commit():
        session = test_db["session_factory"]()
        orig_commit = session.commit

        def failing_commit():
            raise OperationalError("disk I/O error during audit insert", None, None)

        session.commit = failing_commit
        try:
            yield session
        finally:
            session.commit = orig_commit
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db_failing_commit

    try:
        ch = _create_challenge(claimed_identity="Alice", session_id="sess-db-fail-02")

        with patch("app.api.routes_verification._get_run_liveness_check", return_value=lambda p, d: (True, "Passed", "123")):
            with patch("app.api.routes_verification._get_verify_speaker", return_value=lambda **kw: {"is_accepted": False, "similarity": 0.12}):
                response = client.post(
                    "/verify",
                    data={
                        "claimed_identity": "Alice",
                        "challenge_id": ch.challenge_id,
                        "session_id": "sess-db-fail-02",
                    },
                    files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] is False
        assert data["action"] == "DENY"
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_correlation_id_truncation_and_sanitization(test_db, enrolled_speakers):
    """
    12. Correlation ID handling:
        - Long header (>64 chars) is cleanly truncated to 64 chars without DB constraint violation.
    """
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db():
        session = test_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db

    long_correlation_id = "req-" + "a" * 100  # 104 chars

    try:
        ch = _create_challenge(claimed_identity="Alice", session_id="sess-trunc-01")

        with patch("app.api.routes_verification._get_run_liveness_check", return_value=lambda p, d: (True, "Passed", "123")):
            with patch("app.api.routes_verification._get_verify_speaker", return_value=lambda **kw: {"is_accepted": True, "similarity": 0.88}):
                response = client.post(
                    "/verify",
                    data={
                        "claimed_identity": "Alice",
                        "challenge_id": ch.challenge_id,
                        "session_id": "sess-trunc-01",
                    },
                    headers={"X-Request-ID": long_correlation_id},
                    files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                )

        assert response.status_code == 200

        with test_db["session_factory"]() as session:
            events = session.scalars(select(VerificationEvent)).all()
            assert len(events) == 1
            assert len(events[0].request_id) == 64
            assert events[0].request_id == long_correlation_id[:64]
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_zero_sensitive_data_persisted_in_event(test_db, enrolled_speakers):
    """
    13. Data hygiene verification:
        - VerificationEvent model contains no audio bytes, audio paths, embeddings,
          similarity scores, tokens, passwords, or error messages.
    """
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db():
        session = test_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db

    try:
        ch = _create_challenge(claimed_identity="Alice", session_id="sess-sec-01")

        with patch("app.api.routes_verification._get_run_liveness_check", return_value=lambda p, d: (True, "Passed", "123")):
            with patch("app.api.routes_verification._get_verify_speaker", return_value=lambda **kw: {"is_accepted": True, "similarity": 0.88}):
                response = client.post(
                    "/verify",
                    data={
                        "claimed_identity": "Alice",
                        "challenge_id": ch.challenge_id,
                        "session_id": "sess-sec-01",
                    },
                    files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                )

        assert response.status_code == 200

        with test_db["session_factory"]() as session:
            events = session.scalars(select(VerificationEvent)).all()
            assert len(events) == 1
            event = events[0]

            # Allowed columns only
            allowed_cols = {
                "id",
                "created_at",
                "outcome",
                "verification_flow",
                "user_id",
                "speaker_id",
                "device_id",
                "request_id",
            }
            actual_cols = set(VerificationEvent.__table__.columns.keys())
            assert actual_cols == allowed_cols

            # Inspect all string values in the event row
            for col in actual_cols:
                val = getattr(event, col)
                if isinstance(val, str):
                    assert not val.startswith("RIFF"), "Raw audio data detected in audit table!"
                    assert "bearer" not in val.lower(), "Credential detected in audit table!"
                    assert "[" not in val, "Serialized vector/array detected in audit table!"
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_ffmpeg_conversion_failure_records_error_event(test_db, enrolled_speakers):
    """
    14. FFmpeg conversion failure:
        - Challenge is consumed.
        - Processing raises RuntimeError containing 'ffmpeg' or 'conversion failed'.
        - Returns HTTP 400.
        - Persists exactly one event with outcome='error'.
    """
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db():
        session = test_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db

    try:
        ch = _create_challenge(claimed_identity="Alice", session_id="sess-ffmpeg-01")

        with patch("app.api.routes_verification._get_run_liveness_check", side_effect=RuntimeError("FFmpeg conversion failed: Invalid data")):
            response = client.post(
                "/verify",
                data={
                    "claimed_identity": "Alice",
                    "challenge_id": ch.challenge_id,
                    "session_id": "sess-ffmpeg-01",
                },
                files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
            )

        assert response.status_code == 400
        assert "invalid audio stream or unreadable format" in response.json()["detail"].lower()

        with test_db["session_factory"]() as session:
            events = session.scalars(select(VerificationEvent)).all()
            assert len(events) == 1
            assert events[0].outcome == "error"
            assert events[0].speaker_id == "Alice"
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_replaying_consumed_challenge_does_not_create_second_event(test_db, enrolled_speakers):
    """
    15. Challenge replay protection event guarantee:
        - Attempt 1 consumes the challenge and records 1 event.
        - Attempt 2 replays the burned challenge and is rejected with 400 before an attempt is created.
        - Total events in database remains exactly 1.
    """
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db():
        session = test_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db

    try:
        ch = _create_challenge(claimed_identity="Alice", session_id="sess-replay-01")

        with patch("app.api.routes_verification._get_run_liveness_check", return_value=lambda p, d: (True, "Passed", "123")):
            with patch("app.api.routes_verification._get_verify_speaker", return_value=lambda **kw: {"is_accepted": True, "similarity": 0.88}):
                # First attempt: succeeds and records 1 event
                resp1 = client.post(
                    "/verify",
                    data={
                        "claimed_identity": "Alice",
                        "challenge_id": ch.challenge_id,
                        "session_id": "sess-replay-01",
                    },
                    files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                )
                assert resp1.status_code == 200

                # Second attempt with same challenge: rejected with 400
                resp2 = client.post(
                    "/verify",
                    data={
                        "claimed_identity": "Alice",
                        "challenge_id": ch.challenge_id,
                        "session_id": "sess-replay-01",
                    },
                    files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                )
                assert resp2.status_code == 400
                assert "already been consumed" in resp2.json()["detail"].lower()

        # Exactly 1 event exists
        with test_db["session_factory"]() as session:
            events = session.scalars(select(VerificationEvent)).all()
            assert len(events) == 1
            assert events[0].outcome == "verified"
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)
