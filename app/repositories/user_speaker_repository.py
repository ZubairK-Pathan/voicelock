"""
app/repositories/user_speaker_repository.py — Data access repository for UserSpeakerMapping entities.
Encapsulates database operations for mapping authenticated application users (Firebase UID)
to enrolled speaker identities (SpeakerRecord.speaker_id) using SQLAlchemy 2.0.
Transaction boundaries are owned by the caller (session context manager / dependency).
"""

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db.base import UserSpeakerMapping


class UserSpeakerRepositoryError(Exception):
    """Base exception for user-speaker repository errors."""
    pass


class DuplicateUserMappingError(UserSpeakerRepositoryError, ValueError):
    """Raised when attempting to map a user or speaker that already has an existing mapping."""
    pass


class UserMappingNotFoundError(UserSpeakerRepositoryError, KeyError):
    """Raised when a requested user-speaker mapping is not found."""
    pass


class UserSpeakerRepository:
    """
    SQLAlchemy 2.0 repository managing persistence and queries for UserSpeakerMapping.
    Methods operate within the caller's Session and perform flushes where needed,
    leaving transaction commit and rollback control to the caller.
    """

    def __init__(self, session: Session):
        if session is None:
            raise ValueError("UserSpeakerRepository requires an active SQLAlchemy Session.")
        self.session = session

    def create(
        self,
        firebase_uid: str,
        speaker_id: str,
        assigned_by: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ) -> UserSpeakerMapping:
        """
        Create and persist a new UserSpeakerMapping in the database.
        Flushes within a nested savepoint to verify foreign key and uniqueness constraints.
        Does NOT commit or roll back the caller's outer transaction.
        """
        if not firebase_uid or not firebase_uid.strip():
            raise ValueError("firebase_uid must be a non-empty string.")

        if not speaker_id or not speaker_id.strip():
            raise ValueError("speaker_id must be a non-empty string.")

        clean_uid = firebase_uid.strip()
        clean_speaker_id = speaker_id.strip()

        now = datetime.now(timezone.utc)
        record = UserSpeakerMapping(
            firebase_uid=clean_uid,
            speaker_id=clean_speaker_id,
            assigned_by=assigned_by.strip() if assigned_by else None,
            created_at=now,
            updated_at=now,
            metadata_json=metadata_json,
        )

        self.session.add(record)
        try:
            with self.session.begin_nested():
                self.session.flush()
        except IntegrityError as exc:
            raise DuplicateUserMappingError(
                f"Mapping conflict: user '{clean_uid}' or speaker '{clean_speaker_id}' is already mapped or referenced speaker does not exist."
            ) from exc

        return record

    def get_by_firebase_uid(self, firebase_uid: str) -> Optional[UserSpeakerMapping]:
        """
        Retrieve a mapping record by unique Firebase UID.
        Returns None if not found.
        """
        if not firebase_uid:
            return None
        stmt = select(UserSpeakerMapping).where(UserSpeakerMapping.firebase_uid == firebase_uid.strip())
        return self.session.scalar(stmt)

    def get_speaker_id_for_user(self, firebase_uid: str) -> Optional[str]:
        """
        Fast scalar query returning the bound speaker_id for a given Firebase UID.
        Returns None if no mapping exists.
        """
        if not firebase_uid:
            return None
        stmt = select(UserSpeakerMapping.speaker_id).where(UserSpeakerMapping.firebase_uid == firebase_uid.strip())
        return self.session.scalar(stmt)

    def get_by_speaker_id(self, speaker_id: str) -> Optional[UserSpeakerMapping]:
        """
        Retrieve a mapping record by unique enrolled speaker_id.
        Returns None if not found.
        """
        if not speaker_id:
            return None
        stmt = select(UserSpeakerMapping).where(UserSpeakerMapping.speaker_id == speaker_id.strip())
        return self.session.scalar(stmt)

    def get_or_raise(self, firebase_uid: str) -> UserSpeakerMapping:
        """
        Retrieve mapping by firebase_uid, raising UserMappingNotFoundError if not found.
        """
        record = self.get_by_firebase_uid(firebase_uid)
        if record is None:
            raise UserMappingNotFoundError(f"Mapping for user '{firebase_uid}' not found.")
        return record

    def get_by_id(self, mapping_id: int) -> Optional[UserSpeakerMapping]:
        """
        Retrieve a mapping record by its integer primary key.
        Returns None if not found.
        """
        if not mapping_id:
            return None
        return self.session.get(UserSpeakerMapping, mapping_id)

    def delete_by_id(self, mapping_id: int) -> bool:
        """
        Remove mapping by integer primary key.
        Returns True if deleted, False if not found.
        """
        record = self.get_by_id(mapping_id)
        if record is None:
            return False
        self.session.delete(record)
        self.session.flush()
        return True

    def delete_by_firebase_uid(self, firebase_uid: str) -> bool:
        """
        Remove mapping for a user by Firebase UID.
        Returns True if deleted, False if not found.
        """
        record = self.get_by_firebase_uid(firebase_uid)
        if record is None:
            return False
        self.session.delete(record)
        self.session.flush()
        return True

    def delete_by_speaker_id(self, speaker_id: str) -> bool:
        """
        Remove mapping for a speaker by speaker_id.
        Returns True if deleted, False if not found.
        """
        record = self.get_by_speaker_id(speaker_id)
        if record is None:
            return False
        self.session.delete(record)
        self.session.flush()
        return True

    def list_mappings(
        self,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[UserSpeakerMapping]:
        """
        List user-to-speaker mappings ordered alphabetically by firebase_uid.
        Eagerly loads the associated speaker record to avoid N+1 queries.
        """
        stmt = (
            select(UserSpeakerMapping)
            .options(joinedload(UserSpeakerMapping.speaker))
            .order_by(UserSpeakerMapping.firebase_uid)
        )
        if offset > 0:
            stmt = stmt.offset(offset)
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).all())

    def count(self) -> int:
        """Return total number of user-speaker mappings."""
        stmt = select(func.count(UserSpeakerMapping.id))
        return self.session.scalar(stmt) or 0
