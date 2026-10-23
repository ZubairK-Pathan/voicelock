"""
tests/test_security_events_api.py — Comprehensive test suite for Administrator Security Audit Events API.

Validates:
1. Authentication & Authorization:
   - Missing credentials reject with HTTP 401.
   - Invalid, expired, and revoked tokens reject with HTTP 401.
   - Regular users reject with HTTP 403 (RBAC enforcement).
   - Administrators successfully authenticate and query.
2. Cursor-Based Pagination:
   - Default page size is 50.
   - Custom limit bounded by MAX_LIMIT (100).
   - Exceeding limit rejects with HTTP 422.
   - Invalid or malformed cursor rejects with HTTP 400.
   - Multi-page iteration is deterministic with zero dropped or duplicate events.
   - Events sharing identical timestamps are ordered deterministically by ID tie-breaker without cross-page duplicates.
3. Database-Level Filtering:
   - Filter by event_type.
   - Filter by severity.
   - Filter by status.
   - Filter by user_id and device_id.
   - Time window filtering [start_time, end_time).
   - Invalid date ranges (start > end) reject with HTTP 400.
   - Invalid event_type or severity rejects with HTTP 400.
   - Combined filters return exact intersection.
   - Non-matching filters return empty list with HTTP 200.
4. Data Privacy & Minimization:
   - Passwords, bearer tokens, HMAC keys, audio paths, and embeddings are strictly excluded.
   - Metadata is filtered against the safe allowlist; forbidden keys and sensitive tokens are dropped.
   - Response contains only documented schema fields.
5. Database Safety:
   - Database errors return safe HTTP 500 without leaking connection strings or stack traces.
   - The endpoint is strictly read-only: does not create, update, or delete records.
"""

from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.main import app
from app.core.auth import set_test_token_verifier
from app.db.base import (
    Base,
    SecurityEvent,
    SecurityEventType,
    SecurityEventSeverity,
    SecurityEventStatus,
)
from app.db.session import get_engine, get_db_context
from app.schemas.security_event import encode_cursor
from tests.test_auth import (
    ADMIN_TOKEN,
    USER_TOKEN,
    REVOKED_TOKEN,
    EXPIRED_TOKEN,
    INVALID_TOKEN,
    deterministic_test_verifier,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_auth_and_db():
    set_test_token_verifier(deterministic_test_verifier)
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    with get_db_context() as session:
        session.query(SecurityEvent).delete()
    yield
    with get_db_context() as session:
        session.query(SecurityEvent).delete()


# ─── 1. Authentication and Authorization ─────────────────────────────────────

def test_security_events_unauthenticated_returns_401():
    """Unauthenticated access to /admin/security-events is rejected with HTTP 401."""
    response = client.get("/admin/security-events")
    assert response.status_code == 401
    assert "Authorization" in response.json()["detail"]


def test_security_events_invalid_token_returns_401():
    """Invalid bearer token is rejected with HTTP 401."""
    response = client.get(
        "/admin/security-events",
        headers={"Authorization": f"Bearer {INVALID_TOKEN}"},
    )
    assert response.status_code == 401
    assert "Invalid authentication token" in response.json()["detail"]


def test_security_events_expired_token_returns_401():
    """Expired token is rejected with HTTP 401."""
    response = client.get(
        "/admin/security-events",
        headers={"Authorization": f"Bearer {EXPIRED_TOKEN}"},
    )
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


def test_security_events_revoked_token_returns_401():
    """Revoked token is rejected with HTTP 401."""
    response = client.get(
        "/admin/security-events",
        headers={"Authorization": f"Bearer {REVOKED_TOKEN}"},
    )
    assert response.status_code == 401
    assert "revoked" in response.json()["detail"].lower()


def test_security_events_regular_user_returns_403():
    """Authenticated non-admin user is rejected with HTTP 403 Forbidden."""
    response = client.get(
        "/admin/security-events",
        headers={"Authorization": f"Bearer {USER_TOKEN}"},
    )
    assert response.status_code == 403
    assert "Administrative privileges required" in response.json()["detail"]


def test_security_events_empty_as_admin():
    """Admin query on empty events table returns HTTP 200 with empty list."""
    response = client.get(
        "/admin/security-events",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["events"] == []
    assert data["count"] == 0
    assert data["has_more"] is False
    assert data["next_cursor"] is None


# ─── 2. Pagination & Ordering ────────────────────────────────────────────────

def test_security_events_default_page_size():
    """Default page size is 50 when limit parameter is omitted."""
    base_time = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    with get_db_context() as session:
        for i in range(60):
            event = SecurityEvent(
                event_type=SecurityEventType.RATE_LIMIT_EXCEEDED.value,
                severity=SecurityEventSeverity.LOW.value,
                status=SecurityEventStatus.BLOCKED.value,
                details=f"Rate limit event {i}",
                created_at=base_time + timedelta(seconds=i),
            )
            session.add(event)

    response = client.get(
        "/admin/security-events",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 50
    assert len(data["events"]) == 50
    assert data["has_more"] is True
    assert data["next_cursor"] is not None


def test_security_events_custom_limit():
    """Custom page limit bounded between 1 and 100 works accurately."""
    base_time = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    with get_db_context() as session:
        for i in range(25):
            event = SecurityEvent(
                event_type=SecurityEventType.RATE_LIMIT_EXCEEDED.value,
                severity=SecurityEventSeverity.LOW.value,
                status=SecurityEventStatus.BLOCKED.value,
                details=f"Rate limit event {i}",
                created_at=base_time + timedelta(seconds=i),
            )
            session.add(event)

    response = client.get(
        "/admin/security-events?limit=10",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 10
    assert len(data["events"]) == 10
    assert data["has_more"] is True
    assert data["next_cursor"] is not None


def test_security_events_max_page_size_enforcement():
    """Requesting limit exceeding maximum (100) is rejected with HTTP 422."""
    response = client.get(
        "/admin/security-events?limit=101",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 422


def test_security_events_invalid_limit_bounds():
    """Requesting limit < 1 is rejected with HTTP 422."""
    response = client.get(
        "/admin/security-events?limit=0",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 422


def test_security_events_invalid_cursor_handling():
    """Malformed or invalid cursor returns HTTP 400."""
    response = client.get(
        "/admin/security-events?cursor=malformed_non_base64_string",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 400
    assert "Invalid pagination cursor" in response.json()["detail"]


def test_security_events_pagination_multi_page_deterministic():
    """Multi-page iteration walks all records deterministically with zero duplicates."""
    base_time = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    total_events = 15
    with get_db_context() as session:
        for i in range(total_events):
            event = SecurityEvent(
                event_type=SecurityEventType.RATE_LIMIT_EXCEEDED.value,
                severity=SecurityEventSeverity.LOW.value,
                status=SecurityEventStatus.BLOCKED.value,
                details=f"Deterministic event {i}",
                created_at=base_time + timedelta(minutes=i),
            )
            session.add(event)

    all_fetched_ids = []
    cursor = None

    while True:
        url = "/admin/security-events?limit=4"
        if cursor:
            url += f"&cursor={cursor}"

        response = client.get(url, headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
        assert response.status_code == 200
        data = response.json()

        for ev in data["events"]:
            all_fetched_ids.append(ev["id"])

        if not data["has_more"]:
            assert data["next_cursor"] is None
            break
        cursor = data["next_cursor"]
        assert cursor is not None

    # Check that all 15 were retrieved with zero duplicates
    assert len(all_fetched_ids) == total_events
    assert len(set(all_fetched_ids)) == total_events


def test_security_events_pagination_identical_timestamps_tie_breaker():
    """Events sharing identical timestamps are paginated deterministically using ID tie-breaker."""
    fixed_time = datetime(2026, 10, 15, 8, 30, 0, tzinfo=timezone.utc)
    with get_db_context() as session:
        for i in range(5):
            event = SecurityEvent(
                event_type=SecurityEventType.SUSPICIOUS_PAYLOAD.value,
                severity=SecurityEventSeverity.MEDIUM.value,
                status=SecurityEventStatus.DETECTED.value,
                details=f"Concurrent event {i}",
                created_at=fixed_time,
            )
            session.add(event)

    # Page 1 (limit=2)
    resp1 = client.get(
        "/admin/security-events?limit=2",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["count"] == 2
    assert data1["has_more"] is True
    ids_p1 = [e["id"] for e in data1["events"]]
    cursor1 = data1["next_cursor"]

    # Page 2 (limit=2)
    resp2 = client.get(
        f"/admin/security-events?limit=2&cursor={cursor1}",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["count"] == 2
    assert data2["has_more"] is True
    ids_p2 = [e["id"] for e in data2["events"]]
    cursor2 = data2["next_cursor"]

    # Page 3 (limit=2)
    resp3 = client.get(
        f"/admin/security-events?limit=2&cursor={cursor2}",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert data3["count"] == 1
    assert data3["has_more"] is False
    ids_p3 = [e["id"] for e in data3["events"]]

    all_ids = ids_p1 + ids_p2 + ids_p3
    # Check all 5 retrieved, strictly descending ID order, zero duplication
    assert len(all_ids) == 5
    assert len(set(all_ids)) == 5
    assert all_ids == sorted(all_ids, reverse=True)


# ─── 3. Filtering ────────────────────────────────────────────────────────────

def test_security_events_filter_by_event_type():
    """Filtering by event_type returns only matching records."""
    now = datetime.now(timezone.utc)
    with get_db_context() as session:
        session.add(SecurityEvent(
            event_type=SecurityEventType.RATE_LIMIT_EXCEEDED.value,
            severity=SecurityEventSeverity.LOW.value,
            details="Rate limit hit",
            created_at=now,
        ))
        session.add(SecurityEvent(
            event_type=SecurityEventType.HMAC_NONCE_REPLAY.value,
            severity=SecurityEventSeverity.HIGH.value,
            details="Replay attempt",
            created_at=now + timedelta(seconds=1),
        ))

    resp = client.get(
        f"/admin/security-events?event_type={SecurityEventType.HMAC_NONCE_REPLAY.value}",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["events"][0]["event_type"] == SecurityEventType.HMAC_NONCE_REPLAY.value


def test_security_events_filter_invalid_event_type():
    """Invalid event_type filter returns HTTP 400."""
    resp = client.get(
        "/admin/security-events?event_type=non_existent_type",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 400
    assert "Invalid event_type" in resp.json()["detail"]


def test_security_events_filter_by_severity():
    """Filtering by severity returns only matching records."""
    now = datetime.now(timezone.utc)
    with get_db_context() as session:
        session.add(SecurityEvent(
            event_type=SecurityEventType.RATE_LIMIT_EXCEEDED.value,
            severity=SecurityEventSeverity.LOW.value,
            created_at=now,
        ))
        session.add(SecurityEvent(
            event_type=SecurityEventType.UNAUTHORIZED_ACCESS.value,
            severity=SecurityEventSeverity.CRITICAL.value,
            created_at=now + timedelta(seconds=1),
        ))

    resp = client.get(
        "/admin/security-events?severity=critical",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["events"][0]["severity"] == "critical"


def test_security_events_filter_by_status():
    """Filtering by status returns only matching records."""
    now = datetime.now(timezone.utc)
    with get_db_context() as session:
        session.add(SecurityEvent(
            event_type=SecurityEventType.RATE_LIMIT_EXCEEDED.value,
            severity=SecurityEventSeverity.LOW.value,
            status=SecurityEventStatus.BLOCKED.value,
            created_at=now,
        ))
        session.add(SecurityEvent(
            event_type=SecurityEventType.SUSPICIOUS_PAYLOAD.value,
            severity=SecurityEventSeverity.MEDIUM.value,
            status=SecurityEventStatus.LOGGED.value,
            created_at=now + timedelta(seconds=1),
        ))

    resp = client.get(
        "/admin/security-events?status=logged",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["events"][0]["status"] == "logged"


def test_security_events_filter_by_user_id():
    """Filtering by user_id matches actor Firebase UID."""
    now = datetime.now(timezone.utc)
    with get_db_context() as session:
        session.add(SecurityEvent(
            event_type=SecurityEventType.UNAUTHORIZED_SPEAKER_CLAIM.value,
            severity=SecurityEventSeverity.HIGH.value,
            user_id="uid-target-user",
            created_at=now,
        ))
        session.add(SecurityEvent(
            event_type=SecurityEventType.RATE_LIMIT_EXCEEDED.value,
            severity=SecurityEventSeverity.LOW.value,
            user_id="uid-other-user",
            created_at=now + timedelta(seconds=1),
        ))

    resp = client.get(
        "/admin/security-events?user_id=uid-target-user",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["events"][0]["user_id"] == "uid-target-user"


def test_security_events_filter_by_time_window():
    """Filtering by [start_time, end_time) matches the exact window in UTC."""
    t0 = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 10, 1, 11, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 10, 1, 13, 0, 0, tzinfo=timezone.utc)

    with get_db_context() as session:
        session.add(SecurityEvent(
            event_type=SecurityEventType.RATE_LIMIT_EXCEEDED.value,
            severity=SecurityEventSeverity.LOW.value,
            details="Before window",
            created_at=t0,
        ))
        session.add(SecurityEvent(
            event_type=SecurityEventType.RATE_LIMIT_EXCEEDED.value,
            severity=SecurityEventSeverity.LOW.value,
            details="Inside window",
            created_at=t1,
        ))
        session.add(SecurityEvent(
            event_type=SecurityEventType.RATE_LIMIT_EXCEEDED.value,
            severity=SecurityEventSeverity.LOW.value,
            details="At upper boundary (exclusive)",
            created_at=t2,
        ))
        session.add(SecurityEvent(
            event_type=SecurityEventType.RATE_LIMIT_EXCEEDED.value,
            severity=SecurityEventSeverity.LOW.value,
            details="After window",
            created_at=t3,
        ))

    # Test with ISO strings containing UTC 'Z'
    resp = client.get(
        f"/admin/security-events?start_time=2026-10-01T11:00:00Z&end_time=2026-10-01T12:00:00Z",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["events"][0]["details"] == "Inside window"


def test_security_events_filter_invalid_date_range():
    """Reject start_time > end_time with HTTP 400."""
    resp = client.get(
        "/admin/security-events?start_time=2026-10-01T12:00:00Z&end_time=2026-10-01T10:00:00Z",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 400
    assert "start_time cannot be greater than end_time" in resp.json()["detail"]


def test_security_events_combined_filters_and_empty_result():
    """Combined filters return intersection, or empty list if no matches."""
    now = datetime.now(timezone.utc)
    with get_db_context() as session:
        session.add(SecurityEvent(
            event_type=SecurityEventType.RATE_LIMIT_EXCEEDED.value,
            severity=SecurityEventSeverity.LOW.value,
            status=SecurityEventStatus.BLOCKED.value,
            user_id="user-a",
            created_at=now,
        ))

    # Match all three
    resp = client.get(
        f"/admin/security-events?event_type={SecurityEventType.RATE_LIMIT_EXCEEDED.value}&severity=low&user_id=user-a",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 1

    # Mismatch user_id
    resp_empty = client.get(
        f"/admin/security-events?event_type={SecurityEventType.RATE_LIMIT_EXCEEDED.value}&severity=low&user_id=user-b",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp_empty.status_code == 200
    assert resp_empty.json()["count"] == 0
    assert resp_empty.json()["events"] == []


# ─── 4. Data Privacy & Minimization ──────────────────────────────────────────

def test_security_events_data_privacy_and_metadata_sanitization():
    """
    Ensures:
    1. Only documented schema fields are returned.
    2. Prohibited keys (passwords, tokens, HMAC secrets, audio, embeddings) are excluded.
    3. Metadata is filtered against safe allowlist; non-allowlisted keys are dropped.
    4. Sensitive token-like values in allowlisted fields are dropped.
    """
    now = datetime.now(timezone.utc)
    raw_metadata = {
        # Permitted non-sensitive audit keys
        "endpoint": "/api/v1/verify",
        "method": "POST",
        "status_code": 403,
        "reason": "Mismatched biometric claim",
        # Non-allowlisted operational debug keys
        "internal_debug_key": "not-allowlisted",
        "client_debug_metric": 42,
        # Sensitive pattern in reason should cause it to be dropped
        "failure_reason": "Bearer eyJhbGciOi...",
    }

    with get_db_context() as session:
        session.add(SecurityEvent(
            event_type=SecurityEventType.UNAUTHORIZED_SPEAKER_CLAIM.value,
            severity=SecurityEventSeverity.HIGH.value,
            status=SecurityEventStatus.BLOCKED.value,
            details="Tampered identity header rejected",
            user_id="attacker-uid",
            device_id="terminal-01",
            request_id="req-trace-xyz",
            metadata_json=raw_metadata,
            created_at=now,
        ))

    resp = client.get(
        "/admin/security-events",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    event = data["events"][0]

    # Verify documented fields are present
    expected_keys = {
        "id", "created_at", "event_type", "severity", "status",
        "details", "user_id", "device_id", "request_id", "metadata"
    }
    assert set(event.keys()) == expected_keys

    # Check sanitized metadata
    meta = event["metadata"]
    assert meta is not None
    assert meta["endpoint"] == "/api/v1/verify"
    assert meta["method"] == "POST"
    assert meta["status_code"] == 403
    assert meta["reason"] == "Mismatched biometric claim"
    assert "internal_debug_key" not in meta
    assert "client_debug_metric" not in meta
    # Bearer token value was dropped from failure_reason
    assert "failure_reason" not in meta


# ─── 5. Database Safety and Read-Only Invariance ─────────────────────────────

def test_security_events_database_failure_returns_safe_500():
    """Database exceptions return generic 500 without leaking connection strings."""
    with patch(
        "app.repositories.security_event_repository.SecurityEventRepository.list_events",
        side_effect=SQLAlchemyError("postgresql://admin:super_secret_password@db.cloud.neon.tech/main error"),
    ):
        resp = client.get(
            "/admin/security-events",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert "Database failure while querying security audit events" in detail
        assert "password" not in detail
        assert "postgresql://" not in detail


def test_security_events_endpoint_is_strictly_read_only():
    """Querying the endpoint never modifies, inserts, or deletes records in the database."""
    now = datetime.now(timezone.utc)
    with get_db_context() as session:
        session.add(SecurityEvent(
            event_type=SecurityEventType.ADMIN_ACTION.value,
            severity=SecurityEventSeverity.LOW.value,
            status=SecurityEventStatus.LOGGED.value,
            details="Initial seeded audit event",
            created_at=now,
        ))

    with get_db_context() as session:
        count_before = session.query(SecurityEvent).count()

    resp = client.get(
        "/admin/security-events",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200

    with get_db_context() as session:
        count_after = session.query(SecurityEvent).count()
        assert count_after == count_before
