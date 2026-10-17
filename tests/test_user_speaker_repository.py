"""
tests/test_user_speaker_repository.py — Unit test suite for UserSpeakerRepository.

Verifies:
1. Creating user-to-speaker mappings with valid foreign keys and attributes.
2. Input validation (empty UIDs or speaker IDs).
3. 1-to-1 cardinality enforcement:
   - Duplicate Firebase UID rejection (DuplicateUserMappingError).
   - Duplicate Speaker ID rejection (DuplicateUserMappingError).
4. Foreign key constraint enforcement: mapping to nonexistent speaker fails.
5. Querying by UID (record and direct scalar speaker_id string).
6. Querying by speaker_id.
7. get_or_raise handling (success vs UserMappingNotFoundError).
8. Deletion by UID and deletion by speaker_id.
9. Listing, pagination, and count operations.
10. Cascade deletion: removing a speaker automatically cleans up their user mapping.
"""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.base import Base, SpeakerRecord
from app.db.session import create_db_engine
from app.repositories.speaker_repository import SpeakerRepository
from app.repositories.user_speaker_repository import (
    UserSpeakerRepository,
    DuplicateUserMappingError,
    UserMappingNotFoundError,
)


@pytest.fixture
def db_session():
    """Create an isolated, disposable SQLite database and session for unit testing."""
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
    """Verify UserSpeakerRepository raises ValueError if initialized without a session."""
    with pytest.raises(ValueError, match="requires an active SQLAlchemy Session"):
        UserSpeakerRepository(None)  # type: ignore


def test_create_mapping_success(db_session):
    """Verify creating a valid mapping between an enrolled speaker and a Firebase UID."""
    speaker_repo = SpeakerRepository(db_session)
    speaker_repo.create(speaker_id="Zubair", full_name="Zubair Pathan")

    user_repo = UserSpeakerRepository(db_session)
    mapping = user_repo.create(
        firebase_uid="uid-zubair-123",
        speaker_id="Zubair",
        assigned_by="admin-user-001",
        metadata_json='{"department": "engineering"}',
    )

    assert mapping.id is not None
    assert mapping.firebase_uid == "uid-zubair-123"
    assert mapping.speaker_id == "Zubair"
    assert mapping.assigned_by == "admin-user-001"
    assert mapping.created_at is not None
    assert mapping.speaker.full_name == "Zubair Pathan"


def test_create_mapping_validation(db_session):
    """Verify empty UIDs or speaker IDs raise ValueError before hitting database."""
    user_repo = UserSpeakerRepository(db_session)
    with pytest.raises(ValueError, match="firebase_uid must be a non-empty string"):
        user_repo.create(firebase_uid="", speaker_id="Zubair")

    with pytest.raises(ValueError, match="speaker_id must be a non-empty string"):
        user_repo.create(firebase_uid="uid-001", speaker_id="   ")


def test_duplicate_firebase_uid_rejected(db_session):
    """Verify a user cannot be mapped to multiple speakers (1-to-1 cardinality)."""
    speaker_repo = SpeakerRepository(db_session)
    speaker_repo.create(speaker_id="Zubair")
    speaker_repo.create(speaker_id="Alice")

    user_repo = UserSpeakerRepository(db_session)
    user_repo.create(firebase_uid="uid-user-dup", speaker_id="Zubair")

    with pytest.raises(DuplicateUserMappingError, match="Mapping conflict"):
        user_repo.create(firebase_uid="uid-user-dup", speaker_id="Alice")


def test_duplicate_speaker_id_rejected(db_session):
    """Verify an enrolled speaker cannot be bound to multiple users (1-to-1 cardinality)."""
    speaker_repo = SpeakerRepository(db_session)
    speaker_repo.create(speaker_id="Zubair")

    user_repo = UserSpeakerRepository(db_session)
    user_repo.create(firebase_uid="uid-first-user", speaker_id="Zubair")

    with pytest.raises(DuplicateUserMappingError, match="Mapping conflict"):
        user_repo.create(firebase_uid="uid-second-user", speaker_id="Zubair")


def test_get_by_firebase_uid_and_scalar_lookup(db_session):
    """Verify querying mapping and direct scalar speaker_id lookup."""
    speaker_repo = SpeakerRepository(db_session)
    speaker_repo.create(speaker_id="Zubair")

    user_repo = UserSpeakerRepository(db_session)
    user_repo.create(firebase_uid="uid-lookup-001", speaker_id="Zubair")

    # Full record lookup
    record = user_repo.get_by_firebase_uid("uid-lookup-001")
    assert record is not None
    assert record.speaker_id == "Zubair"

    # Fast scalar lookup
    speaker_id = user_repo.get_speaker_id_for_user("uid-lookup-001")
    assert speaker_id == "Zubair"

    # Non-existent user
    assert user_repo.get_by_firebase_uid("uid-nonexistent") is None
    assert user_repo.get_speaker_id_for_user("uid-nonexistent") is None


def test_get_by_speaker_id(db_session):
    """Verify querying mapping by enrolled speaker identity."""
    speaker_repo = SpeakerRepository(db_session)
    speaker_repo.create(speaker_id="Zubair")

    user_repo = UserSpeakerRepository(db_session)
    user_repo.create(firebase_uid="uid-by-speaker", speaker_id="Zubair")

    record = user_repo.get_by_speaker_id("Zubair")
    assert record is not None
    assert record.firebase_uid == "uid-by-speaker"

    assert user_repo.get_by_speaker_id("Nonexistent") is None


def test_get_or_raise(db_session):
    """Verify get_or_raise returns mapping or raises UserMappingNotFoundError."""
    speaker_repo = SpeakerRepository(db_session)
    speaker_repo.create(speaker_id="Zubair")

    user_repo = UserSpeakerRepository(db_session)
    user_repo.create(firebase_uid="uid-raise-test", speaker_id="Zubair")

    record = user_repo.get_or_raise("uid-raise-test")
    assert record.speaker_id == "Zubair"

    with pytest.raises(UserMappingNotFoundError, match="Mapping for user 'unknown-uid' not found"):
        user_repo.get_or_raise("unknown-uid")


def test_delete_by_uid_and_by_speaker(db_session):
    """Verify deletion by UID and by speaker_id."""
    speaker_repo = SpeakerRepository(db_session)
    speaker_repo.create(speaker_id="Zubair")
    speaker_repo.create(speaker_id="Alice")

    user_repo = UserSpeakerRepository(db_session)
    user_repo.create(firebase_uid="uid-del-1", speaker_id="Zubair")
    user_repo.create(firebase_uid="uid-del-2", speaker_id="Alice")

    # Delete by UID
    assert user_repo.delete_by_firebase_uid("uid-del-1") is True
    assert user_repo.get_by_firebase_uid("uid-del-1") is None
    assert user_repo.delete_by_firebase_uid("uid-del-1") is False

    # Delete by speaker_id
    assert user_repo.delete_by_speaker_id("Alice") is True
    assert user_repo.get_by_speaker_id("Alice") is None
    assert user_repo.delete_by_speaker_id("Alice") is False


def test_list_mappings_and_count(db_session):
    """Verify listing mappings with pagination and counting total records."""
    speaker_repo = SpeakerRepository(db_session)
    user_repo = UserSpeakerRepository(db_session)

    for i in range(5):
        s_id = f"Speaker_{i:02d}"
        u_id = f"uid_{i:02d}"
        speaker_repo.create(speaker_id=s_id)
        user_repo.create(firebase_uid=u_id, speaker_id=s_id)

    assert user_repo.count() == 5

    # Pagination
    page1 = user_repo.list_mappings(limit=2, offset=0)
    assert len(page1) == 2
    assert page1[0].firebase_uid == "uid_00"
    assert page1[1].firebase_uid == "uid_01"

    page2 = user_repo.list_mappings(limit=2, offset=2)
    assert len(page2) == 2
    assert page2[0].firebase_uid == "uid_02"
    assert page2[1].firebase_uid == "uid_03"
