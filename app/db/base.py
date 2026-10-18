"""
app/db/base.py — SQLAlchemy 2.0 Declarative Base and foundational migration entity.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates


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
    embedding_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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


class DeviceRecord(Base):
    """
    Durable hardware terminal (IoT access point) registry record.
    Stores device identification, physical location metadata, cryptographic verifier
    (secret hash), key versioning for zero-downtime rotation, and lifecycle status.

    Security & Provisioning Architecture:
    1. Zero Raw Credentials: Raw pre-shared keys and HMAC secrets are NEVER stored
       in the database in plaintext. Only cryptographic hashes / derived verifiers
       are stored in `secret_hash`.
    2. Provisioning Flow: Terminal credentials are generated with high entropy (CSPRNG),
       provisioned directly to device secure storage (e.g. ESP32 secure NVS / eFuse),
       hashed, and stored in the registry.
    3. Rotation Support: `key_version` provides version tracking for graceful credential
       rotation without requiring immediate terminal downtime.
    4. Identity Decoupling: Devices possess Role.DEVICE and cannot verify against user
       mappings or impersonate web users.
    5. Biometric Exclusion: Strictly avoids storing audio, voiceprints, or tokens.
    """
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
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


class VerificationOutcome(str, Enum):
    """
    Bounded outcome categories for biometric verification attempts.
    Mapped directly from verification service execution paths:
    - VERIFIED: Biometric similarity >= threshold AND spoken liveness passed (UNLOCK)
    - REJECTED: Spoken liveness passed, but biometric similarity < threshold (DENY)
    - CHALLENGE_FAILED: Spoken digit liveness check failed (wrong digits, silence, timeout, or reused challenge)
    - UNAUTHORIZED: Caller not authorized to claim target speaker identity (RBAC violation)
    - ERROR: Malformed audio format, decoding error, or processing exception
    """
    VERIFIED = "verified"
    REJECTED = "rejected"
    CHALLENGE_FAILED = "challenge_failed"
    UNAUTHORIZED = "unauthorized"
    ERROR = "error"


VALID_VERIFICATION_OUTCOMES = frozenset(item.value for item in VerificationOutcome)
VALID_VERIFICATION_FLOWS = frozenset({"web", "device"})


class VerificationEvent(Base):
    """
    Durable verification event audit journal entity.
    Records transactional verification attempts, outcomes, and audit telemetry
    without persisting biometric audio, embeddings, similarity scores, or credentials.

    Privacy & Retention Semantics:
    1. Zero Biometric Storage: Raw audio, audio file paths, 192-d embeddings,
       and similarity scores are strictly excluded from persistence.
    2. Zero Credential Storage: Passwords, bearer tokens, and device secrets are strictly excluded.
    3. Audit History Preservation: When a speaker or device is deleted from its registry table,
       the associated historical verification event is retained with foreign keys set to NULL
       (ondelete="SET NULL"), ensuring audit compliance while scrubbing orphaned PII.
    4. Identity Decoupling: user_id records the authenticated Firebase UID (external auth);
       speaker_id references the claimed enrolled voiceprint; device_id references the physical terminal.
    """
    __tablename__ = "verification_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    outcome: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    verification_flow: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="web",
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )
    speaker_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("speakers.speaker_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    device_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("devices.device_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    request_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('verified', 'rejected', 'challenge_failed', 'unauthorized', 'error')",
            name="ck_verification_events_outcome",
        ),
        CheckConstraint(
            "verification_flow IN ('web', 'device')",
            name="ck_verification_events_flow",
        ),
        Index("ix_verification_events_created_outcome", "created_at", "outcome"),
    )

    # Relationships for ORM traversal
    speaker: Mapped[Optional["SpeakerRecord"]] = relationship(
        "SpeakerRecord",
        backref="verification_events",
        passive_deletes=True,
    )
    device: Mapped[Optional["DeviceRecord"]] = relationship(
        "DeviceRecord",
        backref="verification_events",
        passive_deletes=True,
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("verification_flow", "web")
        if "created_at" not in kwargs:
            kwargs["created_at"] = datetime.now(timezone.utc)
        super().__init__(**kwargs)

    @validates("outcome")
    def validate_outcome(self, key: str, value: str) -> str:
        if not value or value not in VALID_VERIFICATION_OUTCOMES:
            raise ValueError(
                f"Invalid verification outcome '{value}'. Must be one of {sorted(VALID_VERIFICATION_OUTCOMES)}."
            )
        return value

    @validates("verification_flow")
    def validate_flow(self, key: str, value: str) -> str:
        if not value or value not in VALID_VERIFICATION_FLOWS:
            raise ValueError(
                f"Invalid verification flow '{value}'. Must be one of {sorted(VALID_VERIFICATION_FLOWS)}."
            )
        return value



