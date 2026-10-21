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

import numpy as np
import pytest
from sqlalchemy.orm import sessionmaker

from audio_utils import cosine_similarity
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


# ─── Embedding Persistence & Retrieval Tests ───────────────────────────────────

def test_create_speaker_with_embedding(db_session):
    """Verify creating a speaker with a 192-d numpy float32 embedding."""
    repo = SpeakerRepository(db_session)
    embedding = np.random.default_rng(123).normal(size=192).astype(np.float32)

    speaker = repo.create(
        speaker_id="Advait",
        full_name="Advait Sharma",
        embedding=embedding,
    )
    db_session.commit()

    assert speaker.embedding_json is not None
    loaded_embedding = repo.get_embedding("Advait")
    assert loaded_embedding is not None
    assert loaded_embedding.shape == (192,)
    assert loaded_embedding.dtype == np.float32
    np.testing.assert_allclose(embedding, loaded_embedding, rtol=1e-5, atol=1e-6)

    # Cosine similarity must be functionally identical
    sim = cosine_similarity(embedding, loaded_embedding)
    assert sim >= 0.999999


def test_create_speaker_with_embedding_json(db_session):
    """Verify creating a speaker with valid pre-serialized embedding JSON string."""
    from app.core.embeddings import serialize_embedding
    repo = SpeakerRepository(db_session)
    embedding = np.ones(192, dtype=np.float32) * 0.1
    emb_json = serialize_embedding(embedding)

    speaker = repo.create(
        speaker_id="Omar",
        full_name="Omar Farooq",
        embedding_json=emb_json,
    )
    db_session.commit()

    loaded = repo.get_embedding("Omar")
    assert loaded is not None
    assert loaded.shape == (192,)
    np.testing.assert_allclose(embedding, loaded, rtol=1e-5, atol=1e-6)


def test_create_speaker_rejects_invalid_embedding(db_session):
    """Verify invalid embedding dimensions, NaN, or malformed JSON raise ValueError on create."""
    repo = SpeakerRepository(db_session)

    # Wrong dimension
    with pytest.raises(ValueError, match="Embedding dimension mismatch: expected 192, got 100"):
        repo.create(speaker_id="BadDim", embedding=np.zeros(100, dtype=np.float32))

    # NaN in embedding
    bad_nan = np.zeros(192, dtype=np.float32)
    bad_nan[5] = np.nan
    with pytest.raises(ValueError, match="Embedding contains non-finite values"):
        repo.create(speaker_id="BadNaN", embedding=bad_nan)

    # Malformed JSON string
    with pytest.raises(ValueError, match="Invalid JSON in embedding payload"):
        repo.create(speaker_id="BadJSON", embedding_json="{malformed}")


def test_get_embedding_missing_or_unknown_speaker(db_session):
    """Verify get_embedding returns None when speaker is unknown or has no embedding."""
    repo = SpeakerRepository(db_session)

    # Unknown speaker returns None
    assert repo.get_embedding("UnknownSpeaker") is None

    # Speaker without embedding returns None
    repo.create(speaker_id="NoEmbeddingUser")
    db_session.commit()
    assert repo.get_embedding("NoEmbeddingUser") is None


def test_set_embedding_updates_existing_speaker(db_session):
    """Verify set_embedding updates embedding and advances updated_at."""
    repo = SpeakerRepository(db_session)
    speaker = repo.create(speaker_id="Parth", full_name="Parth T.")
    db_session.commit()
    created_updated_at = speaker.updated_at

    emb = np.random.default_rng(999).normal(size=192).astype(np.float32)
    updated_speaker = repo.set_embedding("Parth", emb)
    db_session.commit()

    assert updated_speaker.embedding_json is not None
    assert updated_speaker.updated_at >= created_updated_at
    retrieved_emb = repo.get_embedding("Parth")
    assert retrieved_emb is not None
    np.testing.assert_allclose(emb, retrieved_emb, rtol=1e-5, atol=1e-6)


def test_set_embedding_unknown_speaker_raises(db_session):
    """Verify set_embedding raises SpeakerNotFoundError for unknown speaker."""
    repo = SpeakerRepository(db_session)
    with pytest.raises(SpeakerNotFoundError, match="Speaker 'Ghost' not found"):
        repo.set_embedding("Ghost", np.zeros(192, dtype=np.float32))


def test_update_method_with_embedding(db_session):
    """Verify standard update() method can update embedding."""
    repo = SpeakerRepository(db_session)
    repo.create(speaker_id="Umair")
    db_session.commit()

    emb = np.ones(192, dtype=np.float32) * 0.25
    record = repo.update(speaker_id="Umair", embedding=emb)
    db_session.commit()

    assert record is not None
    retrieved = repo.get_embedding("Umair")
    assert retrieved is not None
    np.testing.assert_allclose(emb, retrieved, rtol=1e-5, atol=1e-6)


def test_embedding_transaction_rollback(db_session):
    """Verify caller rollback discards uncommitted embedding modifications."""
    repo = SpeakerRepository(db_session)
    repo.create(speaker_id="RollbackEmbedding")
    db_session.commit()

    emb = np.ones(192, dtype=np.float32) * 0.77
    repo.set_embedding("RollbackEmbedding", emb)

    # Pre-rollback it's accessible
    assert repo.get_embedding("RollbackEmbedding") is not None

    # Caller rolls back
    db_session.rollback()

    # Embedding was not committed
    assert repo.get_embedding("RollbackEmbedding") is None


def test_get_unmapped_active_speakers(db_session):
    """Verify get_unmapped_active_speakers returns only unmapped speakers with active status."""
    from app.repositories.user_speaker_repository import UserSpeakerRepository
    repo = SpeakerRepository(db_session)
    user_repo = UserSpeakerRepository(db_session)

    repo.create(speaker_id="SpeakerA", status="active")
    repo.create(speaker_id="SpeakerB", status="active")
    repo.create(speaker_id="SpeakerC", status="suspended")
    db_session.commit()

    # Initially both active speakers are unmapped
    unmapped = repo.get_unmapped_active_speakers()
    assert [s.speaker_id for s in unmapped] == ["SpeakerA", "SpeakerB"]

    # Map SpeakerA
    user_repo.create(firebase_uid="uid-a", speaker_id="SpeakerA")
    db_session.commit()

    # Now only SpeakerB is returned
    unmapped_after = repo.get_unmapped_active_speakers()
    assert [s.speaker_id for s in unmapped_after] == ["SpeakerB"]

