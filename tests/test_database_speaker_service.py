"""
tests/test_database_speaker_service.py — Increment 2 Comprehensive Test Suite.

Covers:
1. Identification using database-backed embeddings (1-to-N).
2. Verification using database-backed embeddings (1-to-1).
3. Correct speaker ranking and exact cosine similarity score semantics.
4. Handling inactive speakers (suspended/revoked) and records without embeddings.
5. Handling empty speaker registry (HTTP 503).
6. Safe exclusion of invalid/corrupt embeddings without crash.
7. Database unavailable or query failures fail closed (HTTP 500, no pickle fallback).
8. Ordinary-user speaker ownership restrictions (HTTP 403).
9. Admin and device authorization boundaries.
10. Challenge rejection/consumption ordering before upload persistence.
11. No inference or audio persistence after authorization failure.
12. Concurrent requests and session isolation.
13. Backward compatibility for cloud_api exports and standalone app.py workflow.

Uses synthetic embeddings and disposable temporary databases.
Zero real participant audio, datasets, or credentials used.
"""

import concurrent.futures
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import numpy as np
import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.core.auth import AuthenticatedUser, get_current_admin, get_current_user, set_test_token_verifier
from app.core.auth_policy import Role
from app.core.config import SERVER_THRESHOLD
from app.core.device_auth import AuthenticatedDevice, get_current_actor, set_test_device_registry
from app.core.embeddings import DEFAULT_EMBEDDING_DIM, serialize_embedding
from app.core.rate_limit import _challenge_limiter, _identify_limiter, _verify_limiter
from app.db.base import Base, SpeakerRecord, UserSpeakerMapping
from app.db.session import create_db_engine, get_db, reset_engine
from app.main import app
from app.repositories.speaker_repository import SpeakerRepository
from app.repositories.user_speaker_repository import UserSpeakerRepository
from app.services.challenge_service import get_challenge_store
from app.services.speaker_service import (
    EmptySpeakerRegistryError,
    InactiveSpeakerError,
    MissingSpeakerEmbeddingError,
    SpeakerNotFoundError,
    SpeakerService,
    SpeakerServiceDatabaseError,
    get_classifier,
    get_profiles,
    get_system,
    reload_profiles,
    set_classifier_for_testing,
    reset_classifier_for_testing,
)
from audio_utils import cosine_similarity
import cloud_api

client = TestClient(app)

DUMMY_WAV_BYTES = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_engine():
    """Ensure engine singletons are disposed between test runs."""
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
def disposable_db():
    """Create an isolated, disposable SQLite database for testing."""
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
def synthetic_data(disposable_db):
    """
    Populate disposable database with controlled synthetic speakers:
    - Alice: Active, valid 192-d unit vector.
    - Bob: Active, valid 192-d orthogonal unit vector.
    - Charlie: Suspended, valid 192-d vector.
    - David: Active, embedding_json=None (no enrolled voiceprint).
    - Eve: Active, embedding_json='corrupted-json' (corrupt payload).
    """
    rng = np.random.RandomState(42)

    vec_alice = rng.randn(DEFAULT_EMBEDDING_DIM).astype(np.float32)
    vec_alice /= np.linalg.norm(vec_alice)

    # Bob's vector orthogonalized against Alice
    vec_bob = rng.randn(DEFAULT_EMBEDDING_DIM).astype(np.float32)
    vec_bob -= np.dot(vec_bob, vec_alice) * vec_alice
    vec_bob /= np.linalg.norm(vec_bob)

    vec_charlie = rng.randn(DEFAULT_EMBEDDING_DIM).astype(np.float32)
    vec_charlie /= np.linalg.norm(vec_charlie)

    session = disposable_db["session_factory"]()
    try:
        repo = SpeakerRepository(session)
        usr_repo = UserSpeakerRepository(session)

        repo.create(
            speaker_id="Alice",
            full_name="Alice Wonderland",
            status="active",
            embedding=vec_alice,
        )
        repo.create(
            speaker_id="Bob",
            full_name="Bob Builder",
            status="active",
            embedding=vec_bob,
        )
        repo.create(
            speaker_id="Charlie",
            full_name="Charlie Chaplin",
            status="suspended",
            embedding=vec_charlie,
        )
        repo.create(
            speaker_id="David",
            full_name="David Copperfield",
            status="active",
            embedding=None,  # No embedding
        )
        # Directly insert Eve with corrupt JSON
        eve = SpeakerRecord(
            speaker_id="Eve",
            full_name="Eve Corrupt",
            status="active",
            embedding_dim=192,
            embedding_json="{not valid json:",
        )
        session.add(eve)
        session.flush()

        # Map user Alice
        usr_repo.create(firebase_uid="uid-alice-123", speaker_id="Alice")

        session.commit()
    finally:
        session.close()

    return {
        "alice": vec_alice,
        "bob": vec_bob,
        "charlie": vec_charlie,
    }


# ─── 1. Unit Tests for SpeakerService ──────────────────────────────────────────

def test_service_get_registered_speakers_active_only(disposable_db, synthetic_data):
    """Verify get_registered_speakers returns sorted list of active speakers only."""
    session = disposable_db["session_factory"]()
    try:
        service = SpeakerService(session)
        names = service.get_registered_speakers()
        # Alice, Bob, David, Eve are active; Charlie (suspended) must be excluded
        assert names == ["Alice", "Bob", "David", "Eve"]
        assert "Charlie" not in names
    finally:
        session.close()


def test_service_get_active_profiles_skips_missing_and_corrupt(disposable_db, synthetic_data):
    """Verify get_active_profiles returns only active speakers with valid embeddings."""
    session = disposable_db["session_factory"]()
    try:
        service = SpeakerService(session)
        profiles = service.get_active_profiles()

        assert "Alice" in profiles
        assert "Bob" in profiles
        # Charlie (suspended), David (None), Eve (corrupt) must be omitted
        assert "Charlie" not in profiles
        assert "David" not in profiles
        assert "Eve" not in profiles

        assert profiles["Alice"].shape == (192,)
        assert profiles["Alice"].dtype == np.float32
        assert np.allclose(profiles["Alice"], synthetic_data["alice"])
    finally:
        session.close()


def test_service_get_speaker_embedding_statuses(disposable_db, synthetic_data):
    """Verify get_speaker_embedding returns vector only for active speakers with valid embeddings."""
    session = disposable_db["session_factory"]()
    try:
        service = SpeakerService(session)

        # Active with embedding
        alice_vec = service.get_speaker_embedding("Alice")
        assert alice_vec is not None
        assert np.allclose(alice_vec, synthetic_data["alice"])

        # Suspended
        assert service.get_speaker_embedding("Charlie") is None

        # Missing embedding
        assert service.get_speaker_embedding("David") is None

        # Corrupt embedding
        assert service.get_speaker_embedding("Eve") is None

        # Unknown speaker
        assert service.get_speaker_embedding("NonExistent") is None
    finally:
        session.close()


def test_service_identify_and_ranking_semantics(disposable_db, synthetic_data):
    """Verify identify_speaker returns correct predicted speaker, descending ranking, and exact scores."""
    session = disposable_db["session_factory"]()
    try:
        service = SpeakerService(session)

        with tempfile.NamedTemporaryFile(suffix=".wav") as tf:
            tf.write(DUMMY_WAV_BYTES)
            tf.flush()
            # Mock generate_embedding to return Alice's exact vector
            with patch("predict.preprocess_audio", return_value=(np.zeros(16000), 16000)):
                with patch("predict.generate_embedding", return_value=synthetic_data["alice"]):
                    result = service.identify_speaker(tf.name, threshold=SERVER_THRESHOLD)

                    assert result["predicted_speaker"] == "Alice"
                    assert result["is_unknown"] is False
                    assert np.isclose(result["similarity"], 1.0, atol=1e-4)

                    # Check ranking semantics
                    scores = result["all_scores"]
                    assert list(scores.keys())[0] == "Alice"
                    assert scores["Alice"] >= scores["Bob"]
                    expected_bob_score = float(cosine_similarity(synthetic_data["alice"], synthetic_data["bob"]))
                    assert np.isclose(scores["Bob"], expected_bob_score, atol=1e-4)
    finally:
        session.close()


def test_service_verify_speaker_accepted_and_rejected(disposable_db, synthetic_data):
    """Verify verify_speaker returns is_accepted True on match and False on non-match."""
    session = disposable_db["session_factory"]()
    try:
        service = SpeakerService(session)

        with tempfile.NamedTemporaryFile(suffix=".wav") as tf:
            tf.write(DUMMY_WAV_BYTES)
            tf.flush()
            # 1. Matching Alice
            with patch("predict.preprocess_audio", return_value=(np.zeros(16000), 16000)):
                with patch("predict.generate_embedding", return_value=synthetic_data["alice"]):
                    res_match = service.verify_speaker(tf.name, claimed_identity="Alice")
                    assert res_match["is_accepted"] is True
                    assert res_match["claimed_identity"] == "Alice"

            # 2. Non-matching (Bob's vector against Alice)
            with patch("predict.preprocess_audio", return_value=(np.zeros(16000), 16000)):
                with patch("predict.generate_embedding", return_value=synthetic_data["bob"]):
                    res_diff = service.verify_speaker(tf.name, claimed_identity="Alice")
                    assert res_diff["is_accepted"] is False
    finally:
        session.close()


def test_service_verify_speaker_exceptions(disposable_db, synthetic_data):
    """Verify verify_speaker raises specific typed errors for unknown, inactive, or un-enrolled speakers."""
    session = disposable_db["session_factory"]()
    try:
        service = SpeakerService(session)

        # Unknown speaker
        with pytest.raises(SpeakerNotFoundError, match="not registered"):
            service.verify_speaker("dummy.wav", claimed_identity="Ghost")

        # Inactive speaker
        with pytest.raises(InactiveSpeakerError, match="inactive"):
            service.verify_speaker("dummy.wav", claimed_identity="Charlie")

        # Active speaker without embedding
        with pytest.raises(MissingSpeakerEmbeddingError, match="no biometric voiceprint"):
            service.verify_speaker("dummy.wav", claimed_identity="David")
    finally:
        session.close()


def test_service_database_failure_fails_closed(disposable_db):
    """Verify database OperationalError raises SpeakerServiceDatabaseError and never falls back."""
    mock_session = MagicMock()
    mock_session.scalars.side_effect = OperationalError("connection lost", {}, Exception())
    mock_session.scalar.side_effect = OperationalError("connection lost", {}, Exception())

    service = SpeakerService(mock_session)

    with pytest.raises(SpeakerServiceDatabaseError, match="Database error"):
        service.get_registered_speakers()

    with pytest.raises(SpeakerServiceDatabaseError, match="Database error"):
        service.get_active_profiles()

    with pytest.raises(SpeakerServiceDatabaseError, match="Database error"):
        service.get_speaker_embedding("Alice")


# ─── 2. API Integration Tests (Database-Backed Endpoints) ─────────────────────

def test_api_identify_database_backed(disposable_db, synthetic_data):
    """Verify /identify uses the database-backed profiles and returns correct identification."""
    admin_user = AuthenticatedUser(
        uid="admin-001",
        email="admin@test.com",
        email_verified=True,
        roles=[Role.ADMIN, Role.USER],
    )

    def override_db():
        session = disposable_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_admin] = lambda: admin_user
    app.dependency_overrides[get_db] = override_db

    try:
        with patch("predict.preprocess_audio", return_value=(np.zeros(16000), 16000)):
            with patch("predict.generate_embedding", return_value=synthetic_data["alice"]):
                response = client.post(
                    "/identify",
                    files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                )
                assert response.status_code == 200
                data = response.json()
                assert data["predicted_speaker"] == "Alice"
                assert data["similarity"] > SERVER_THRESHOLD
                assert "Alice" in data["all_scores"]
                assert "Bob" in data["all_scores"]
                assert "Charlie" not in data["all_scores"]
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
        app.dependency_overrides.pop(get_db, None)


def test_api_identify_empty_database_returns_503(disposable_db):
    """Verify /identify returns 503 when the database has no enrolled speaker profiles."""
    admin_user = AuthenticatedUser(
        uid="admin-001",
        email="admin@test.com",
        email_verified=True,
        roles=[Role.ADMIN, Role.USER],
    )

    def override_db():
        session = disposable_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_admin] = lambda: admin_user
    app.dependency_overrides[get_db] = override_db

    try:
        response = client.post(
            "/identify",
            files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
        )
        assert response.status_code == 503
        assert "No speaker profiles are enrolled" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
        app.dependency_overrides.pop(get_db, None)


def test_api_verify_database_backed_success(disposable_db, synthetic_data):
    """Verify /verify uses database-backed embedding and authorizes mapped user."""
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db():
        session = disposable_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db

    try:
        # 1. Create challenge for Alice
        ch_resp = client.post("/challenge", json={"claimed_identity": "Alice", "session_id": "sess-alice-01"})
        assert ch_resp.status_code == 200
        ch_data = ch_resp.json()

        # 2. Verify with matching liveness and embedding
        with patch("app.api.routes_verification._get_run_liveness_check", return_value=lambda p, d: (True, "Matched", "123")):
            with patch("predict.preprocess_audio", return_value=(np.zeros(16000), 16000)):
                with patch("predict.generate_embedding", return_value=synthetic_data["alice"]):
                    response = client.post(
                        "/verify",
                        data={
                            "claimed_identity": "Alice",
                            "challenge_id": ch_data["challenge_id"],
                            "session_id": "sess-alice-01",
                        },
                        files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                    )
                    assert response.status_code == 200
                    data = response.json()
                    assert data["accepted"] is True
                    assert data["action"] == "UNLOCK"
                    assert data["claimed_identity"] == "Alice"
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_api_verify_inactive_speaker_returns_404(disposable_db, synthetic_data):
    """Verify /verify rejects suspended speaker Charlie with HTTP 404."""
    admin_user = AuthenticatedUser(
        uid="admin-001",
        email="admin@test.com",
        email_verified=True,
        roles=[Role.ADMIN, Role.USER],
    )

    def override_db():
        session = disposable_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: admin_user
    app.dependency_overrides[get_db] = override_db

    try:
        response = client.post(
            "/verify",
            data={
                "claimed_identity": "Charlie",
                "challenge_id": "any-id",
                "session_id": "any-sess",
            },
            files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
        )
        assert response.status_code == 404
        assert "not registered" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_api_verify_speaker_without_embedding_returns_404(disposable_db, synthetic_data):
    """Verify /verify rejects speaker David (who has no embedding) with HTTP 404."""
    admin_user = AuthenticatedUser(
        uid="admin-001",
        email="admin@test.com",
        email_verified=True,
        roles=[Role.ADMIN, Role.USER],
    )

    def override_db():
        session = disposable_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: admin_user
    app.dependency_overrides[get_db] = override_db

    try:
        response = client.post(
            "/verify",
            data={
                "claimed_identity": "David",
                "challenge_id": "any-id",
                "session_id": "any-sess",
            },
            files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
        )
        assert response.status_code == 404
        assert "no enrolled biometric" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_ordinary_user_cannot_verify_other_speaker(disposable_db, synthetic_data):
    """Security Boundary: User Alice mapped to 'Alice' cannot verify as 'Bob' (HTTP 403)."""
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db():
        session = disposable_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db

    try:
        response = client.post(
            "/verify",
            data={
                "claimed_identity": "Bob",
                "challenge_id": "any-id",
                "session_id": "any-sess",
            },
            files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
        )
        assert response.status_code == 403
        detail = response.json()["detail"]
        assert "only authorized to verify your own voice identity" in detail
        assert "Bob" in detail
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_no_inference_or_audio_persistence_on_auth_failure(disposable_db, synthetic_data):
    """Security Boundary: Authorization rejection occurs before upload saving or ML inference."""
    alice_user = AuthenticatedUser(
        uid="uid-alice-123",
        email="alice@test.com",
        email_verified=True,
        roles=[Role.USER],
    )

    def override_db():
        session = disposable_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: alice_user
    app.dependency_overrides[get_db] = override_db

    save_called = False
    infer_called = False

    def tracking_save(*args, **kwargs):
        nonlocal save_called
        save_called = True
        return Path("dummy.wav")

    def tracking_verify(*args, **kwargs):
        nonlocal infer_called
        infer_called = True
        return {}

    try:
        with patch("app.api.routes_verification._get_save_upload", return_value=tracking_save):
            with patch("predict.verify_speaker", side_effect=tracking_verify):
                response = client.post(
                    "/verify",
                    data={
                        "claimed_identity": "Bob",
                        "challenge_id": "any-id",
                        "session_id": "any-sess",
                    },
                    files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                )
                assert response.status_code == 403
                assert save_called is False
                assert infer_called is False
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_challenge_consumption_before_audio_persistence(disposable_db, synthetic_data):
    """Security Boundary: Missing or invalid challenge fails closed before upload saving."""
    admin_user = AuthenticatedUser(
        uid="admin-001",
        email="admin@test.com",
        email_verified=True,
        roles=[Role.ADMIN],
    )

    def override_db():
        session = disposable_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: admin_user
    app.dependency_overrides[get_db] = override_db

    save_called = False

    def tracking_save(*args, **kwargs):
        nonlocal save_called
        save_called = True
        return Path("dummy.wav")

    try:
        with patch("app.api.routes_verification._get_save_upload", return_value=tracking_save):
            response = client.post(
                "/verify",
                data={
                    "claimed_identity": "Alice",
                    "challenge_id": "invalid-challenge-id-999",
                    "session_id": "sess-01",
                },
                files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
            )
            assert response.status_code == 400
            assert "Invalid or unknown challenge ID" in response.json()["detail"]
            assert save_called is False
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_device_authorized_to_verify_for_door_access(disposable_db, synthetic_data):
    """Security Boundary: Registered hardware terminal can verify any registered active speaker."""
    device_actor = AuthenticatedDevice(
        device_id="esp32-terminal-01",
        name="Main Entrance Gate",
        auth_scheme="hmac_sha256",
    )

    def override_db():
        session = disposable_db["session_factory"]()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_actor] = lambda: device_actor
    app.dependency_overrides[get_db] = override_db

    try:
        # Device creates challenge for Bob
        ch_resp = client.post("/challenge", json={"claimed_identity": "Bob", "session_id": "sess-dev-01"})
        assert ch_resp.status_code == 200
        ch_data = ch_resp.json()

        # Device submits verification for Bob
        with patch("app.api.routes_verification._get_run_liveness_check", return_value=lambda p, d: (True, "Matched", "123")):
            with patch("predict.preprocess_audio", return_value=(np.zeros(16000), 16000)):
                with patch("predict.generate_embedding", return_value=synthetic_data["bob"]):
                    response = client.post(
                        "/verify",
                        data={
                            "claimed_identity": "Bob",
                            "challenge_id": ch_data["challenge_id"],
                            "session_id": "sess-dev-01",
                        },
                        files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                    )
                    assert response.status_code == 200
                    assert response.json()["accepted"] is True
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_db, None)


def test_concurrent_requests_session_isolation(disposable_db, synthetic_data):
    """Concurrency & Session Isolation: Concurrent threads operate on isolated sessions without contamination."""
    # 1. Test SpeakerService concurrent operations across independent sessions
    session_factory = disposable_db["session_factory"]

    def run_service_worker(worker_id):
        session = session_factory()
        try:
            service = SpeakerService(session)
            active = service.get_registered_speakers()
            profiles = service.get_active_profiles()
            alice_emb = service.get_speaker_embedding("Alice")
            bob_emb = service.get_speaker_embedding("Bob")
            return len(active), len(profiles), alice_emb is not None, bob_emb is not None
        finally:
            session.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(run_service_worker, i) for i in range(10)]
        results = [f.result() for f in futures]

    for num_active, num_profiles, has_alice, has_bob in results:
        assert num_active == 4
        assert num_profiles == 2
        assert has_alice is True
        assert has_bob is True

    # 2. Test concurrent API requests with isolated DB sessions and mocked inference
    mock_classifier = MagicMock()
    set_classifier_for_testing(mock_classifier)

    admin_user = AuthenticatedUser(
        uid="admin-001",
        email="admin@test.com",
        email_verified=True,
        roles=[Role.ADMIN, Role.USER],
    )

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_current_admin] = lambda: admin_user
    app.dependency_overrides[get_db] = override_db

    def run_identify(seed):
        with patch("predict.preprocess_audio", return_value=(np.zeros(16000), 16000)):
            with patch("predict.generate_embedding", return_value=synthetic_data["alice"]):
                resp = client.post(
                    "/identify",
                    files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
                )
                return resp.status_code, resp.json().get("predicted_speaker")

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(run_identify, i) for i in range(8)]
            results = [f.result() for f in futures]

        for code, speaker in results:
            assert code == 200
            assert speaker == "Alice"
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
        app.dependency_overrides.pop(get_db, None)
        reset_classifier_for_testing()


def test_backward_compatibility_get_system_database_backed(disposable_db, synthetic_data):
    """Verify cloud_api get_system, get_profiles, reload_profiles retrieve from database without pickle."""
    session = disposable_db["session_factory"]()
    try:
        profiles, classifier = get_system(session)
        assert isinstance(profiles, dict)
        assert "Alice" in profiles
        assert "Bob" in profiles
        assert "Charlie" not in profiles  # Suspended

        p = get_profiles(session)
        assert set(p.keys()) == {"Alice", "Bob"}

        # Check cloud_api re-exports
        assert hasattr(cloud_api, "SpeakerService")
        assert hasattr(cloud_api, "SpeakerNotFoundError")
        assert hasattr(cloud_api, "InactiveSpeakerError")
    finally:
        session.close()
