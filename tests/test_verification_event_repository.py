"""
tests/test_verification_event_repository.py — Unit test suite for VerificationEventRepository (Increment 3C.2).

Tests:
1. Enforcement of non-null Session initialization.
2. Event creation and generated integer ID.
3. Caller-controlled transaction behavior (flushes without committing, rollback cancels persistence).
4. Retrieval of existing and missing IDs (get_event and get_or_raise).
5. Pagination, limit boundaries, and deterministic ordering (newest first: created_at DESC, id DESC).
6. Outcome and verification flow filtering (accepting string and Enum).
7. UTC time-window filtering adhering strictly to [start_time, end_time) interval convention.
8. Invalid date range rejection (start_time > end_time raises ValueError).
9. Invalid pagination parameter rejection (limit <= 0, limit > 500, offset < 0).
10. Aggregate count_events queries for empty and populated databases with filters.
11. Aggregate count_by_outcome grouped queries over time windows.
12. Validation of outcome and verification flow inputs.
13. Identity and correlation field support (user_id, speaker_id, device_id, request_id).
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.base import (
    Base,
    SpeakerRecord,
    DeviceRecord,
    VerificationEvent,
    VerificationOutcome,
    VALID_VERIFICATION_OUTCOMES,
)
from app.db.session import create_db_engine
from app.repositories.verification_event_repository import (
    VerificationEventRepository,
    VerificationEventNotFoundError,
)


@pytest.fixture
def db_session():
    """Create an isolated, disposable SQLite database and session for each unit test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        tmp_db_path = Path(tmp_file.name)

    db_url = f"sqlite:///{tmp_db_path}"
    engine = create_db_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        if tmp_db_path.exists():
            try:
                tmp_db_path.unlink()
            except OSError:
                pass


def test_repository_requires_active_session():
    """Verify repository raises ValueError if initialized with None session."""
    with pytest.raises(ValueError, match="requires an active SQLAlchemy Session"):
        VerificationEventRepository(None)


def test_create_event_success_and_defaults(db_session):
    """Verify creating a verification event with defaults and generated integer ID."""
    repo = VerificationEventRepository(db_session)
    event = repo.create_event(outcome="verified")

    assert event.id is not None
    assert event.id > 0
    assert event.outcome == "verified"
    assert event.verification_flow == "web"
    assert event.created_at is not None
    assert event.created_at.tzinfo == timezone.utc
    assert event.user_id is None
    assert event.speaker_id is None
    assert event.device_id is None
    assert event.request_id is None


def test_create_event_with_enum_and_optional_identities(db_session):
    """Verify creating an event with VerificationOutcome enum and all optional identity fields."""
    repo = VerificationEventRepository(db_session)

    # Pre-populate referenced speaker and device
    speaker = SpeakerRecord(speaker_id="Zubair", full_name="Zubair K. Pathan")
    device = DeviceRecord(device_id="esp32-gate-01", name="Front Gate", secret_hash="hash")
    db_session.add_all([speaker, device])
    db_session.flush()

    fixed_time = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
    event = repo.create_event(
        outcome=VerificationOutcome.REJECTED,
        verification_flow="device",
        user_id="firebase_uid_test",
        speaker_id="Zubair",
        device_id="esp32-gate-01",
        request_id="req-uuid-12345",
        created_at=fixed_time,
    )
    db_session.commit()

    assert event.id is not None
    assert event.outcome == "rejected"
    assert event.verification_flow == "device"
    assert event.user_id == "firebase_uid_test"
    assert event.speaker_id == "Zubair"
    assert event.device_id == "esp32-gate-01"
    assert event.request_id == "req-uuid-12345"
    assert event.created_at is not None
    assert (
        event.created_at == fixed_time
        or event.created_at.replace(tzinfo=timezone.utc) == fixed_time
    )


def test_caller_controlled_transaction_rollback(db_session):
    """Verify repository flushes to expose generated ID without committing, allowing caller rollback."""
    repo = VerificationEventRepository(db_session)
    event = repo.create_event(outcome="verified", request_id="req-rollback-test")
    event_id = event.id

    assert event_id is not None
    # Transaction is not committed yet; caller issues rollback
    db_session.rollback()

    # Querying after rollback must return None
    assert repo.get_event(event_id) is None


def test_get_event_and_get_or_raise(db_session):
    """Verify retrieving existing and non-existent verification events."""
    repo = VerificationEventRepository(db_session)
    event = repo.create_event(outcome="challenge_failed")
    db_session.commit()

    # Existing event retrieval
    loaded = repo.get_event(event.id)
    assert loaded is not None
    assert loaded.id == event.id
    assert loaded.outcome == "challenge_failed"

    # get_or_raise with existing event
    raised = repo.get_or_raise(event.id)
    assert raised.id == event.id

    # Non-existent ID returns None
    assert repo.get_event(999999) is None
    assert repo.get_event(-1) is None
    assert repo.get_event(None) is None

    # get_or_raise with non-existent ID raises VerificationEventNotFoundError
    with pytest.raises(VerificationEventNotFoundError, match="Verification event with ID 999999 not found"):
        repo.get_or_raise(999999)


def test_pagination_and_deterministic_ordering(db_session):
    """Verify limit, offset, and deterministic newest-first ordering (created_at DESC, id DESC)."""
    repo = VerificationEventRepository(db_session)
    base_time = datetime(2026, 10, 19, 10, 0, 0, tzinfo=timezone.utc)

    # Insert 5 events spaced by 1 minute
    for i in range(5):
        repo.create_event(
            outcome="verified",
            request_id=f"req-{i}",
            created_at=base_time + timedelta(minutes=i),
        )
    db_session.commit()

    # Default ordering: newest first (req-4, req-3, req-2, req-1, req-0)
    all_events = repo.list_events(limit=10)
    assert len(all_events) == 5
    assert [e.request_id for e in all_events] == ["req-4", "req-3", "req-2", "req-1", "req-0"]

    # Limit and offset pagination
    page1 = repo.list_events(limit=2, offset=0)
    assert len(page1) == 2
    assert [e.request_id for e in page1] == ["req-4", "req-3"]

    page2 = repo.list_events(limit=2, offset=2)
    assert len(page2) == 2
    assert [e.request_id for e in page2] == ["req-2", "req-1"]

    page3 = repo.list_events(limit=2, offset=4)
    assert len(page3) == 1
    assert [e.request_id for e in page3] == ["req-0"]

    page_empty = repo.list_events(limit=2, offset=10)
    assert len(page_empty) == 0


def test_invalid_pagination_parameters(db_session):
    """Verify limit and offset boundary validation."""
    repo = VerificationEventRepository(db_session)

    with pytest.raises(ValueError, match="limit must be between 1 and 500"):
        repo.list_events(limit=0)

    with pytest.raises(ValueError, match="limit must be between 1 and 500"):
        repo.list_events(limit=501)

    with pytest.raises(ValueError, match="offset must be non-negative"):
        repo.list_events(offset=-1)


def test_outcome_and_flow_filtering(db_session):
    """Verify list_events and count_events with outcome and verification_flow filters."""
    repo = VerificationEventRepository(db_session)

    repo.create_event(outcome="verified", verification_flow="web", request_id="ev-1")
    repo.create_event(outcome="rejected", verification_flow="web", request_id="ev-2")
    repo.create_event(outcome="rejected", verification_flow="device", request_id="ev-3")
    repo.create_event(outcome="challenge_failed", verification_flow="web", request_id="ev-4")
    repo.create_event(outcome="error", verification_flow="device", request_id="ev-5")
    db_session.commit()

    # Filter by outcome string
    rejected_events = repo.list_events(outcome="rejected")
    assert len(rejected_events) == 2
    assert repo.count_events(outcome="rejected") == 2

    # Filter by outcome Enum
    rejected_enum = repo.list_events(outcome=VerificationOutcome.REJECTED)
    assert len(rejected_enum) == 2

    # Filter by flow
    device_events = repo.list_events(verification_flow="device")
    assert len(device_events) == 2
    assert repo.count_events(verification_flow="device") == 2

    # Filter by outcome AND flow
    device_rejected = repo.list_events(outcome="rejected", verification_flow="device")
    assert len(device_rejected) == 1
    assert device_rejected[0].request_id == "ev-3"
    assert repo.count_events(outcome="rejected", verification_flow="device") == 1


def test_time_window_filtering_boundary_semantics(db_session):
    """
    Verify time-window filtering strictly enforces [start_time, end_time) interval:
    - start_time is inclusive (created_at >= start_time)
    - end_time is exclusive (created_at < end_time)
    """
    repo = VerificationEventRepository(db_session)
    t0 = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 10, 19, 12, 30, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 19, 13, 0, 0, tzinfo=timezone.utc)

    repo.create_event(outcome="verified", request_id="ev-t0", created_at=t0)
    repo.create_event(outcome="verified", request_id="ev-t1", created_at=t1)
    repo.create_event(outcome="verified", request_id="ev-t2", created_at=t2)
    db_session.commit()

    # Window [t0, t2) must include t0 and t1, but strictly exclude t2
    window_events = repo.list_events(start_time=t0, end_time=t2)
    assert len(window_events) == 2
    request_ids = [e.request_id for e in window_events]
    assert "ev-t0" in request_ids
    assert "ev-t1" in request_ids
    assert "ev-t2" not in request_ids
    assert repo.count_events(start_time=t0, end_time=t2) == 2

    # Window [t1, t2) must include t1, but exclude t0 and t2
    sub_window = repo.list_events(start_time=t1, end_time=t2)
    assert len(sub_window) == 1
    assert sub_window[0].request_id == "ev-t1"
    assert repo.count_events(start_time=t1, end_time=t2) == 1

    # Naive datetime handling: automatically interpreted as UTC
    t0_naive = datetime(2026, 10, 19, 12, 0, 0)
    t2_naive = datetime(2026, 10, 19, 13, 0, 0)
    naive_events = repo.list_events(start_time=t0_naive, end_time=t2_naive)
    assert len(naive_events) == 2


def test_invalid_date_range_rejection(db_session):
    """Verify start_time > end_time raises ValueError in all time-filtering methods."""
    repo = VerificationEventRepository(db_session)
    earlier = datetime(2026, 10, 19, 10, 0, 0, tzinfo=timezone.utc)
    later = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="start_time cannot be greater than end_time"):
        repo.list_events(start_time=later, end_time=earlier)

    with pytest.raises(ValueError, match="start_time cannot be greater than end_time"):
        repo.count_events(start_time=later, end_time=earlier)

    with pytest.raises(ValueError, match="start_time cannot be greater than end_time"):
        repo.count_by_outcome(start_time=later, end_time=earlier)


def test_count_events_empty_and_filtered(db_session):
    """Verify count_events on empty database and with identity filters."""
    repo = VerificationEventRepository(db_session)
    assert repo.count_events() == 0

    repo.create_event(outcome="verified", user_id="user-a", speaker_id="spk-1", device_id="dev-1")
    repo.create_event(outcome="rejected", user_id="user-a", speaker_id="spk-1", device_id="dev-2")
    repo.create_event(outcome="verified", user_id="user-b", speaker_id="spk-2", device_id="dev-1")
    db_session.commit()

    assert repo.count_events() == 3
    assert repo.count_events(user_id="user-a") == 2
    assert repo.count_events(speaker_id="spk-1") == 2
    assert repo.count_events(device_id="dev-1") == 2
    assert repo.count_events(user_id="user-b", outcome="verified") == 1
    assert repo.count_events(user_id="missing-user") == 0


def test_count_by_outcome_aggregate_grouping(db_session):
    """
    Verify count_by_outcome returns complete dictionary with all valid outcome keys,
    reflecting accurate counts in empty and populated states, with optional time-window
    and flow filtering.
    """
    repo = VerificationEventRepository(db_session)

    # 1. Empty database: all outcomes exist with 0 count
    empty_counts = repo.count_by_outcome()
    assert set(empty_counts.keys()) == VALID_VERIFICATION_OUTCOMES
    assert all(val == 0 for val in empty_counts.values())

    # 2. Populate events across multiple outcomes and times
    t0 = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 10, 19, 12, 30, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 19, 13, 0, 0, tzinfo=timezone.utc)

    repo.create_event(outcome="verified", verification_flow="web", created_at=t0)
    repo.create_event(outcome="verified", verification_flow="web", created_at=t0)
    repo.create_event(outcome="verified", verification_flow="device", created_at=t1)
    repo.create_event(outcome="rejected", verification_flow="web", created_at=t1)
    repo.create_event(outcome="challenge_failed", verification_flow="web", created_at=t1)
    repo.create_event(outcome="unauthorized", verification_flow="web", created_at=t2)
    repo.create_event(outcome="error", verification_flow="device", created_at=t2)
    db_session.commit()

    # Total counts across entire history
    all_counts = repo.count_by_outcome()
    assert all_counts["verified"] == 3
    assert all_counts["rejected"] == 1
    assert all_counts["challenge_failed"] == 1
    assert all_counts["unauthorized"] == 1
    assert all_counts["error"] == 1

    # Filtered by flow
    device_counts = repo.count_by_outcome(verification_flow="device")
    assert device_counts["verified"] == 1
    assert device_counts["error"] == 1
    assert device_counts["rejected"] == 0

    # Filtered by time window [t0, t2) (excludes t2)
    window_counts = repo.count_by_outcome(start_time=t0, end_time=t2)
    assert window_counts["verified"] == 3
    assert window_counts["rejected"] == 1
    assert window_counts["challenge_failed"] == 1
    # unauthorized and error occurred at t2, so excluded
    assert window_counts["unauthorized"] == 0
    assert window_counts["error"] == 0


def test_input_validation_rejections(db_session):
    """Verify create_event, list_events, count_events, count_by_outcome reject invalid inputs."""
    repo = VerificationEventRepository(db_session)

    # Invalid outcomes in create_event
    with pytest.raises(ValueError, match="Invalid outcome 'unknown'"):
        repo.create_event(outcome="unknown")

    with pytest.raises(ValueError, match="Invalid outcome ''"):
        repo.create_event(outcome="")

    # Invalid flow in create_event
    with pytest.raises(ValueError, match="Invalid verification_flow 'mobile'"):
        repo.create_event(outcome="verified", verification_flow="mobile")

    # Invalid outcome in list_events
    with pytest.raises(ValueError, match="Invalid outcome 'fake'"):
        repo.list_events(outcome="fake")

    # Invalid flow in list_events
    with pytest.raises(ValueError, match="Invalid verification_flow 'fake_flow'"):
        repo.list_events(verification_flow="fake_flow")

    # Invalid flow in count_by_outcome
    with pytest.raises(ValueError, match="Invalid verification_flow 'api'"):
        repo.count_by_outcome(verification_flow="api")
