"""
tests/test_metrics_api.py — Comprehensive test suite for Admin Verification Metrics API (Increment 3C.4).

Verifies:
1. Administrative RBAC enforcement on /metrics/verification and /metrics.
2. Rejection of unauthenticated, ordinary-user (Role.USER), and device requests.
3. Rejection of expired and revoked admin tokens.
4. Consistent zero-valued aggregates on empty database.
5. Mixed outcome aggregation and exact success-rate denominator calculation.
   (Excluding processing errors from the denominator).
6. Non-zero error handling with zero biometric attempts (avoids division by zero).
7. Bounded UTC time-window filtering adhering strictly to [start_time, end_time) convention.
8. Rejection of invalid time windows (start_time > end_time -> 400).
9. Verification flow isolation ('web' vs 'device').
10. Rejection of invalid verification flow values (400).
11. Data minimization guarantee: zero PII, event IDs, speaker IDs, device IDs, or audio/vector data exposed.
12. Fail-closed database failure handling with sanitized 500 responses.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from app.core.auth import set_test_token_verifier
from app.db.base import Base, DeviceRecord, SpeakerRecord, VerificationEvent, VerificationOutcome
from app.db.session import get_db_context, get_engine
from app.main import app
from app.repositories.verification_event_repository import VerificationEventRepository
from tests.test_auth import (
    ADMIN_TOKEN,
    EXPIRED_TOKEN,
    INVALID_TOKEN,
    REVOKED_TOKEN,
    USER_TOKEN,
    deterministic_test_verifier,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_auth_and_db():
    set_test_token_verifier(deterministic_test_verifier)
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    with get_db_context() as session:
        # Clean verification events table before and after each test
        session.query(VerificationEvent).delete()
    yield
    with get_db_context() as session:
        session.query(VerificationEvent).delete()


# ---------------------------------------------------------------------------
# RBAC & Authentication Tests
# ---------------------------------------------------------------------------


def test_metrics_admin_access_empty_database():
    """Admin access succeeds on /metrics/verification and /metrics returning consistent zero-valued schema."""
    for path in ("/metrics/verification", "/metrics"):
        response = client.get(path, headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
        assert response.status_code == 200, f"Failed on path {path}: {response.text}"
        data = response.json()
        assert data["total"] == 0
        assert data["verified"] == 0
        assert data["rejected"] == 0
        assert data["challenge_failed"] == 0
        assert data["error"] == 0
        assert data["success_rate"] == 0.0
        assert data["start_time"] is None
        assert data["end_time"] is None
        assert data["verification_flow"] is None


def test_metrics_unauthenticated_denied():
    """Unauthenticated requests without headers are rejected with HTTP 401."""
    for path in ("/metrics/verification", "/metrics"):
        response = client.get(path)
        assert response.status_code == 401


def test_metrics_ordinary_user_forbidden():
    """Ordinary users with Role.USER are rejected with HTTP 403 Forbidden."""
    for path in ("/metrics/verification", "/metrics"):
        response = client.get(path, headers={"Authorization": f"Bearer {USER_TOKEN}"})
        assert response.status_code == 403
        assert "Forbidden" in response.json()["detail"] or "Admin role required" in response.json()["detail"]


def test_metrics_device_identity_denied():
    """Device headers (without valid admin bearer token) cannot access metrics."""
    headers = {
        "X-Device-ID": "esp32-terminal-01",
        "X-Device-Key": "test_pre_shared_key",
    }
    for path in ("/metrics/verification", "/metrics"):
        response = client.get(path, headers=headers)
        assert response.status_code == 401


def test_metrics_expired_or_invalid_tokens():
    """Expired and invalid tokens are rejected with HTTP 401."""
    for token in (EXPIRED_TOKEN, INVALID_TOKEN):
        response = client.get("/metrics/verification", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401


def test_metrics_revoked_admin_token_denied():
    """Revoked admin tokens are rejected with HTTP 401 via check_revoked=True."""
    response = client.get("/metrics/verification", headers={"Authorization": f"Bearer {REVOKED_TOKEN}"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Aggregation & Denominator Accuracy Tests
# ---------------------------------------------------------------------------


def test_metrics_mixed_outcomes_and_exact_denominator():
    """
    Test mixed outcomes:
    5 verified, 3 rejected, 2 challenge_failed, 4 error.
    Total = 14.
    Success rate denominator = verified (5) + rejected (3) + challenge_failed (2) = 10.
    Success rate = (5 / 10) * 100 = 50.0%.
    Processing errors (4) must be excluded from denominator.
    """
    with get_db_context() as session:
        repo = VerificationEventRepository(session)
        for _ in range(5):
            repo.create_event(outcome=VerificationOutcome.VERIFIED)
        for _ in range(3):
            repo.create_event(outcome=VerificationOutcome.REJECTED)
        for _ in range(2):
            repo.create_event(outcome=VerificationOutcome.CHALLENGE_FAILED)
        for _ in range(4):
            repo.create_event(outcome=VerificationOutcome.ERROR)

    response = client.get("/metrics/verification", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 14
    assert data["verified"] == 5
    assert data["rejected"] == 3
    assert data["challenge_failed"] == 2
    assert data["error"] == 4
    assert data["success_rate"] == 50.0


def test_metrics_zero_biometric_attempts_with_errors():
    """
    When verified, rejected, and challenge_failed are all 0, but error > 0,
    the denominator is 0, so success_rate must return 0.0 without division by zero.
    """
    with get_db_context() as session:
        repo = VerificationEventRepository(session)
        for _ in range(3):
            repo.create_event(outcome=VerificationOutcome.ERROR)

    response = client.get("/metrics/verification", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["verified"] == 0
    assert data["rejected"] == 0
    assert data["challenge_failed"] == 0
    assert data["error"] == 3
    assert data["success_rate"] == 0.0


# ---------------------------------------------------------------------------
# Filtering Tests (Time Window & Flow)
# ---------------------------------------------------------------------------


def test_metrics_time_window_filtering_inclusive_exclusive():
    """
    Adheres strictly to [start_time, end_time) interval convention.
    """
    t_10 = datetime(2026, 10, 19, 10, 0, 0, tzinfo=timezone.utc)
    t_11 = datetime(2026, 10, 19, 11, 0, 0, tzinfo=timezone.utc)
    t_12 = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
    t_13 = datetime(2026, 10, 19, 13, 0, 0, tzinfo=timezone.utc)

    with get_db_context() as session:
        repo = VerificationEventRepository(session)
        # Event 1: 10:00 - verified (outside, before)
        repo.create_event(outcome=VerificationOutcome.VERIFIED, created_at=t_10)
        # Event 2: 11:00 - rejected (included: at start)
        repo.create_event(outcome=VerificationOutcome.REJECTED, created_at=t_11)
        # Event 3: 12:00 - error (included: inside)
        repo.create_event(outcome=VerificationOutcome.ERROR, created_at=t_12)
        # Event 4: 13:00 - verified (excluded: at end)
        repo.create_event(outcome=VerificationOutcome.VERIFIED, created_at=t_13)

    params = {
        "start_time": "2026-10-19T11:00:00Z",
        "end_time": "2026-10-19T13:00:00Z",
    }
    response = client.get(
        "/metrics/verification",
        params=params,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["verified"] == 0
    assert data["rejected"] == 1
    assert data["error"] == 1
    assert data["challenge_failed"] == 0
    assert data["success_rate"] == 0.0


def test_metrics_invalid_time_window_returns_400():
    """start_time > end_time must return HTTP 400 Bad Request."""
    params = {
        "start_time": "2026-10-19T15:00:00Z",
        "end_time": "2026-10-19T12:00:00Z",
    }
    response = client.get(
        "/metrics/verification",
        params=params,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 400
    assert "start_time cannot be greater than end_time" in response.json()["detail"]


def test_metrics_verification_flow_filtering():
    """Flow filtering isolates 'web' vs 'device' records."""
    with get_db_context() as session:
        repo = VerificationEventRepository(session)
        # 3 web events: 2 verified, 1 rejected
        repo.create_event(outcome=VerificationOutcome.VERIFIED, verification_flow="web")
        repo.create_event(outcome=VerificationOutcome.VERIFIED, verification_flow="web")
        repo.create_event(outcome=VerificationOutcome.REJECTED, verification_flow="web")

        # 2 device events: 1 verified, 1 challenge_failed
        repo.create_event(outcome=VerificationOutcome.VERIFIED, verification_flow="device")
        repo.create_event(outcome=VerificationOutcome.CHALLENGE_FAILED, verification_flow="device")

    # Test web filter
    res_web = client.get(
        "/metrics/verification?verification_flow=web",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert res_web.status_code == 200
    data_web = res_web.json()
    assert data_web["total"] == 3
    assert data_web["verified"] == 2
    assert data_web["rejected"] == 1
    assert data_web["challenge_failed"] == 0
    assert data_web["verification_flow"] == "web"
    assert data_web["success_rate"] == 66.67

    # Test device filter
    res_dev = client.get(
        "/metrics/verification?verification_flow=device",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert res_dev.status_code == 200
    data_dev = res_dev.json()
    assert data_dev["total"] == 2
    assert data_dev["verified"] == 1
    assert data_dev["rejected"] == 0
    assert data_dev["challenge_failed"] == 1
    assert data_dev["verification_flow"] == "device"
    assert data_dev["success_rate"] == 50.0


def test_metrics_invalid_flow_returns_400():
    """Supplying an unknown verification_flow returns HTTP 400."""
    response = client.get(
        "/metrics/verification?verification_flow=telepathic",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 400
    assert "Invalid verification_flow" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Data Minimization & Security Tests
# ---------------------------------------------------------------------------


def test_metrics_data_minimization_guarantee():
    """
    Strictly verifies that response contains ONLY aggregate data:
    Zero event IDs, user IDs, speaker IDs, device IDs, request IDs,
    individual timestamps, audio paths, embeddings, or scores.
    """
    with get_db_context() as session:
        # Pre-seed referenced speaker and device
        speaker = SpeakerRecord(speaker_id="SensitiveSpeaker123", full_name="Sensitive Speaker")
        device = DeviceRecord(device_id="vault-terminal-secret", name="Vault", secret_hash="secret_hash_value")
        session.add_all([speaker, device])
        session.flush()

        repo = VerificationEventRepository(session)
        repo.create_event(
            outcome=VerificationOutcome.VERIFIED,
            verification_flow="device",
            user_id="sensitive_user_uid_999",
            speaker_id="SensitiveSpeaker123",
            device_id="vault-terminal-secret",
            request_id="req_confidential_uuid_xyz",
        )

    response = client.get("/metrics/verification", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert response.status_code == 200
    raw_text = response.text

    # Verify sensitive identity and correlation strings are absent
    assert "SensitiveSpeaker123" not in raw_text
    assert "Sensitive Speaker" not in raw_text
    assert "vault-terminal-secret" not in raw_text
    assert "secret_hash_value" not in raw_text
    assert "sensitive_user_uid_999" not in raw_text
    assert "req_confidential_uuid_xyz" not in raw_text

    # Verify no raw biometric metadata or database internal fields are exposed
    assert "embedding" not in raw_text.lower()
    assert "similarity" not in raw_text.lower()
    assert "score" not in raw_text.lower()
    assert "audio" not in raw_text.lower()

    # Verify exact schema keys
    data = response.json()
    expected_keys = {
        "total",
        "verified",
        "rejected",
        "challenge_failed",
        "error",
        "success_rate",
        "start_time",
        "end_time",
        "verification_flow",
    }
    assert set(data.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Fail-Closed Error Handling Tests
# ---------------------------------------------------------------------------


def test_metrics_database_failure_fails_closed():
    """Database failures return sanitized HTTP 500 without leaking stack traces or internal SQL."""
    with patch(
        "app.api.routes_metrics.VerificationEventRepository.count_by_outcome",
        side_effect=RuntimeError("Internal SQL connection timeout to primary cluster"),
    ):
        response = client.get("/metrics/verification", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
        assert response.status_code == 500
        assert "Database failure while retrieving verification metrics." in response.json()["detail"]
        assert "primary cluster" not in response.text
        assert "Internal SQL connection" not in response.text
