"""
app/db/base.py — SQLAlchemy 2.0 Declarative Base and foundational migration entity.
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """
    Base class for all VoiceLock Enterprise declarative database models.
    Provides standard SQLAlchemy 2.0 declarative metadata.
    """
    pass


class SchemaInitialization(Base):
    """
    Minimal schema verification entity demonstrating database connectivity
    and migration execution integrity without premature business entity modeling.
    Production domain tables (speakers, devices, challenges, audits) are introduced in 3C.2-3C.5.
    """
    __tablename__ = "schema_initializations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    initialized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SpeakerRecord(Base):
    """
    Durable speaker identity registry record.
    Stores registered speaker identity metadata, enrollment parameters,
    and lifecycle status while raw 192-d biometric vectors are preserved
    in speaker_profiles/profiles.pkl.
    """
    __tablename__ = "speakers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    speaker_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, default=192, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    @property
    def is_active(self) -> bool:
        return self.status == "active"


class UserSpeakerMapping(Base):
    """
    Durable mapping between an authenticated application user (Firebase UID)
    and an enrolled biometric voiceprint identity (SpeakerRecord.speaker_id).

    Cardinality Decision:
    - 1-to-1 relationship enforced via UNIQUE constraints on both firebase_uid and speaker_id.
    - Rationale: Non-repudiation in biometric authentication requires that an individual's
      voiceprint cannot be shared across multiple user accounts, and an ordinary user account
      cannot verify on behalf of multiple enrolled speaker identities.
    - Foreign key referential integrity: speaker_id references speakers.speaker_id with ON DELETE CASCADE.
    - Sensitive data exclusion: never stores Firebase passwords, ID tokens, service keys, or raw audio/embeddings.
    """
    __tablename__ = "user_speaker_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    speaker_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("speakers.speaker_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    assigned_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ORM relationship for bidirectional traversal
    speaker: Mapped["SpeakerRecord"] = relationship("SpeakerRecord", backref="user_mapping")


