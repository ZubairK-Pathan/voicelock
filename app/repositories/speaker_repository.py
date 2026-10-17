"""
app/repositories/speaker_repository.py — Data access repository for SpeakerRecord entities.
Encapsulates all database operations on the speakers table using SQLAlchemy 2.0.
Decoupled from FastAPI HTTP routes and presentation logic.
Transaction boundaries are owned by the caller (session context manager / dependency).
"""

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import SpeakerRecord


class SpeakerRepositoryError(Exception):
    """Base exception for speaker repository errors."""
    pass


class DuplicateSpeakerError(SpeakerRepositoryError, ValueError):
    """Raised when attempting to create a speaker with an existing speaker_id."""
    pass


class SpeakerNotFoundError(SpeakerRepositoryError, KeyError):
    """Raised when a requested speaker cannot be found."""
    pass


class SpeakerRepository:
    """
    SQLAlchemy 2.0 repository managing persistence and queries for SpeakerRecord.
    Methods operate within the caller's Session and perform flushes where needed,
    leaving transaction commit and rollback control to the caller.
    """

    VALID_STATUSES = frozenset({"active", "suspended", "revoked"})

    def __init__(self, session: Session):
        if session is None:
            raise ValueError("SpeakerRepository requires an active SQLAlchemy Session.")
        self.session = session

    def create(
        self,
        speaker_id: str,
        full_name: Optional[str] = None,
        status: str = "active",
        embedding_dim: int = 192,
        sample_count: int = 1,
        metadata_json: Optional[str] = None,
    ) -> SpeakerRecord:
        """
        Create and persist a new SpeakerRecord in the database.
        Flushes to the database transaction to populate autoincrement ID and verify constraints.
        Does NOT commit the transaction.
        """
        if not speaker_id or not speaker_id.strip():
            raise ValueError("speaker_id must be a non-empty string.")

        clean_speaker_id = speaker_id.strip()

        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Must be one of {sorted(self.VALID_STATUSES)}.")

        if embedding_dim <= 0:
            raise ValueError("embedding_dim must be a positive integer.")

        if sample_count < 1:
            raise ValueError("sample_count must be at least 1.")

        now = datetime.now(timezone.utc)
        record = SpeakerRecord(
            speaker_id=clean_speaker_id,
            full_name=full_name.strip() if full_name else None,
            status=status,
            embedding_dim=embedding_dim,
            sample_count=sample_count,
            created_at=now,
            updated_at=now,
            metadata_json=metadata_json,
        )

        self.session.add(record)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise DuplicateSpeakerError(
                f"Speaker with speaker_id '{clean_speaker_id}' already exists."
            ) from exc

        return record

    def get_by_speaker_id(self, speaker_id: str) -> Optional[SpeakerRecord]:
        """
        Retrieve a speaker by their unique speaker_id.
        Returns None if no matching record is found.
        """
        if not speaker_id:
            return None
        stmt = select(SpeakerRecord).where(SpeakerRecord.speaker_id == speaker_id.strip())
        return self.session.scalar(stmt)

    def get_by_id(self, record_id: int) -> Optional[SpeakerRecord]:
        """
        Retrieve a speaker by primary key integer ID.
        """
        return self.session.get(SpeakerRecord, record_id)

    def get_or_raise(self, speaker_id: str) -> SpeakerRecord:
        """
        Retrieve a speaker by speaker_id, raising SpeakerNotFoundError if not found.
        """
        record = self.get_by_speaker_id(speaker_id)
        if record is None:
            raise SpeakerNotFoundError(f"Speaker '{speaker_id}' not found.")
        return record

    def list_speakers(
        self,
        active_only: bool = False,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[SpeakerRecord]:
        """
        List speakers ordered alphabetically by speaker_id.
        Optionally filters for active speakers only and supports pagination.
        """
        stmt = select(SpeakerRecord).order_by(SpeakerRecord.speaker_id)
        if active_only:
            stmt = stmt.where(SpeakerRecord.status == "active")
        if offset > 0:
            stmt = stmt.offset(offset)
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)

        return list(self.session.scalars(stmt).all())

    def get_active_speaker_ids(self) -> List[str]:
        """
        Return a sorted list of unique speaker_id strings for all active speakers.
        Useful for quick identity checks against biometric profiles.
        """
        stmt = (
            select(SpeakerRecord.speaker_id)
            .where(SpeakerRecord.status == "active")
            .order_by(SpeakerRecord.speaker_id)
        )
        return list(self.session.scalars(stmt).all())

    def update(
        self,
        speaker_id: str,
        full_name: Optional[str] = None,
        status: Optional[str] = None,
        sample_count: Optional[int] = None,
        metadata_json: Optional[str] = None,
    ) -> Optional[SpeakerRecord]:
        """
        Update permitted metadata and lifecycle fields of an existing speaker.
        Returns the updated record, or None if the speaker does not exist.
        Flushes changes to the session without committing.
        """
        record = self.get_by_speaker_id(speaker_id)
        if record is None:
            return None

        if full_name is not None:
            record.full_name = full_name.strip() if full_name else None

        if status is not None:
            if status not in self.VALID_STATUSES:
                raise ValueError(f"Invalid status '{status}'. Must be one of {sorted(self.VALID_STATUSES)}.")
            record.status = status

        if sample_count is not None:
            if sample_count < 1:
                raise ValueError("sample_count must be at least 1.")
            record.sample_count = sample_count

        if metadata_json is not None:
            record.metadata_json = metadata_json

        record.updated_at = datetime.now(timezone.utc)
        self.session.flush()
        return record

    def delete(self, speaker_id: str) -> bool:
        """
        Remove a speaker record from the database.
        Returns True if deleted, False if the speaker was not found.
        Flushes deletion to the session without committing.
        """
        record = self.get_by_speaker_id(speaker_id)
        if record is None:
            return False

        self.session.delete(record)
        self.session.flush()
        return True

    def count(self, active_only: bool = False) -> int:
        """
        Return total number of speaker records, optionally filtered by active status.
        """
        stmt = select(func.count(SpeakerRecord.id))
        if active_only:
            stmt = stmt.where(SpeakerRecord.status == "active")
        return self.session.scalar(stmt) or 0
