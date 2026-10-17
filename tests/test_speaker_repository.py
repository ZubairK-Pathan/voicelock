"""
tests/test_speaker_repository.py — Unit test suite for SpeakerRepository (Milestone 3C.2b).

Tests:
1. Creating speaker records with valid attributes and default values.
2. Input validation (empty IDs, invalid status, invalid dimensions/sample count).
3. Duplicate speaker ID rejection (DuplicateSpeakerError via database constraint).
4. Retrieval by speaker_id and integer primary key.
5. Missing record handling (None vs SpeakerNotFoundError via get_or_raise).
6. Listing speakers, pagination (limit/offset), and active-only filtering.
7. get_active_speaker_ids convenience lookup.
8. Updating speaker metadata, lifecycle status, and timestamp updates.
9. Deleting speaker records and verifying cleanup.
10. Explicit transaction boundaries and caller-controlled rollback.
11. Enforcement of non-null Session initialization.
"""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.base import Base, SpeakerRecord
from app.db.session import create_db_engine
from app.repositories.speaker_repository import (
    SpeakerRepository,
    DuplicateSpeakerError,
    SpeakerNotFoundError,
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
    """Verify SpeakerRepository raises ValueError if initialized without a session."""
    with pytest.raises(ValueError, match="requires an active SQLAlchemy Session"):
        SpeakerRepository(None)


def test_create_speaker_success(db_session):
    """Verify creating a speaker record with valid attributes and defaults."""
    repo = SpeakerRepository(db_session)
    speaker = repo.create(
        speaker_id="Zubair",
        full_name="Zubair K. Pathan",
        status="active",
        embedding_dim=192,
        sample_count=3,
        metadata_json='{"device": "macbook_pro"}',
    )
    db_session.commit()

    assert speaker.id is not None
    assert speaker.speaker_id == "Zubair"
    assert speaker.full_name == "Zubair K. Pathan"
    assert speaker.status == "active"
    assert speaker.is_active is True
    assert speaker.embedding_dim == 192
    assert speaker.sample_count == 3
    assert speaker.metadata_json == '{"device": "macbook_pro"}'
    assert speaker.created_at is not None
    assert speaker.updated_at is not None


def test_create_speaker_input_validation(db_session):
    """Verify input validation rules on create."""
    repo = SpeakerRepository(db_session)

    # Empty / whitespace ID
    with pytest.raises(ValueError, match="speaker_id must be a non-empty string"):
        repo.create(speaker_id="")
    with pytest.raises(ValueError, match="speaker_id must be a non-empty string"):
        repo.create(speaker_id="   ")

    # Invalid status
    with pytest.raises(ValueError, match="Invalid status 'unknown'"):
        repo.create(speaker_id="Alice", status="unknown")

    # Non-positive embedding_dim
    with pytest.raises(ValueError, match="embedding_dim must be a positive integer"):
        repo.create(speaker_id="Alice", embedding_dim=0)

    # Invalid sample_count
    with pytest.raises(ValueError, match="sample_count must be at least 1"):
        repo.create(speaker_id="Alice", sample_count=0)


def test_create_duplicate_speaker_raises_error(db_session):
    """Verify unique constraint triggers DuplicateSpeakerError."""
    repo = SpeakerRepository(db_session)
    repo.create(speaker_id="Omar", full_name="Omar Al-Faruq")
    db_session.commit()

    with pytest.raises(DuplicateSpeakerError, match="already exists"):
        repo.create(speaker_id="Omar", full_name="Duplicate Omar")


def test_get_by_speaker_id_and_id(db_session):
    """Verify retrieval by speaker_id and primary key ID."""
    repo = SpeakerRepository(db_session)
    created = repo.create(speaker_id="Parth", full_name="Parth Sharma")
    db_session.commit()

    # By speaker_id
    found = repo.get_by_speaker_id("Parth")
    assert found is not None
    assert found.speaker_id == "Parth"
    assert found.full_name == "Parth Sharma"

    # By ID
    found_by_id = repo.get_by_id(created.id)
    assert found_by_id is not None
    assert found_by_id.speaker_id == "Parth"

    # Non-existent
    assert repo.get_by_speaker_id("NonExistent") is None
    assert repo.get_by_speaker_id("") is None
    assert repo.get_by_id(999999) is None


def test_get_or_raise_behavior(db_session):
    """Verify get_or_raise returns record or raises SpeakerNotFoundError."""
    repo = SpeakerRepository(db_session)
    repo.create(speaker_id="Advait", full_name="Advait Patel")
    db_session.commit()

    record = repo.get_or_raise("Advait")
    assert record.speaker_id == "Advait"

    with pytest.raises(SpeakerNotFoundError, match="Speaker 'Ghost' not found"):
        repo.get_or_raise("Ghost")


def test_list_speakers_and_active_filtering(db_session):
    """Verify listing speakers, pagination, and active-only filtering."""
    repo = SpeakerRepository(db_session)

    # Seed 4 speakers in mixed order and statuses
    repo.create(speaker_id="Zara", status="active")
    repo.create(speaker_id="Bob", status="suspended")
    repo.create(speaker_id="Alice", status="active")
    repo.create(speaker_id="Charlie", status="revoked")
    db_session.commit()

    # All speakers (sorted by speaker_id)
    all_speakers = repo.list_speakers(active_only=False)
    assert len(all_speakers) == 4
    assert [s.speaker_id for s in all_speakers] == ["Alice", "Bob", "Charlie", "Zara"]

    # Active only
    active_speakers = repo.list_speakers(active_only=True)
    assert len(active_speakers) == 2
    assert [s.speaker_id for s in active_speakers] == ["Alice", "Zara"]

    # Active IDs list
    active_ids = repo.get_active_speaker_ids()
    assert active_ids == ["Alice", "Zara"]

    # Pagination: limit
    limited = repo.list_speakers(active_only=False, limit=2)
    assert [s.speaker_id for s in limited] == ["Alice", "Bob"]

    # Pagination: offset
    offset_list = repo.list_speakers(active_only=False, offset=2)
    assert [s.speaker_id for s in offset_list] == ["Charlie", "Zara"]


def test_update_speaker_success(db_session):
    """Verify permitted metadata and status updates."""
    repo = SpeakerRepository(db_session)
    speaker = repo.create(speaker_id="Shreyas", full_name="Shreyas K", status="active")
    db_session.commit()
    initial_updated_at = speaker.updated_at

    updated = repo.update(
        speaker_id="Shreyas",
        full_name="Shreyas Kumar",
        status="suspended",
        sample_count=5,
        metadata_json='{"verified": true}',
    )
    db_session.commit()

    assert updated is not None
    assert updated.full_name == "Shreyas Kumar"
    assert updated.status == "suspended"
    assert updated.is_active is False
    assert updated.sample_count == 5
    assert updated.metadata_json == '{"verified": true}'
    assert updated.updated_at >= initial_updated_at

    # Update non-existent returns None
    assert repo.update("Nobody", status="active") is None


def test_update_speaker_invalid_status(db_session):
    """Verify invalid status during update raises ValueError."""
    repo = SpeakerRepository(db_session)
    repo.create(speaker_id="Umair")
    db_session.commit()

    with pytest.raises(ValueError, match="Invalid status 'banned'"):
        repo.update(speaker_id="Umair", status="banned")


def test_delete_speaker(db_session):
    """Verify deleting a speaker record."""
    repo = SpeakerRepository(db_session)
    repo.create(speaker_id="TempUser")
    db_session.commit()

    assert repo.get_by_speaker_id("TempUser") is not None

    deleted = repo.delete("TempUser")
    db_session.commit()
    assert deleted is True

    # Confirm deletion
    assert repo.get_by_speaker_id("TempUser") is None

    # Deleting non-existent returns False
    assert repo.delete("TempUser") is False


def test_count_speakers(db_session):
    """Verify total and active speaker counts."""
    repo = SpeakerRepository(db_session)
    assert repo.count() == 0

    repo.create(speaker_id="S1", status="active")
    repo.create(speaker_id="S2", status="suspended")
    repo.create(speaker_id="S3", status="active")
    db_session.commit()

    assert repo.count(active_only=False) == 3
    assert repo.count(active_only=True) == 2


def test_caller_controlled_transaction_rollback(db_session):
    """
    Verify that SpeakerRepository operations do NOT commit automatically,
    allowing caller to roll back changes cleanly.
    """
    repo = SpeakerRepository(db_session)
    repo.create(speaker_id="RollbackCandidate", full_name="Should Not Persist")

    # Record is accessible in uncommitted transaction
    assert repo.get_by_speaker_id("RollbackCandidate") is not None

    # Caller explicitly rolls back
    db_session.rollback()

    # Record was not committed and is gone
    assert repo.get_by_speaker_id("RollbackCandidate") is None
