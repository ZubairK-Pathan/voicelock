"""
app/db/base.py — SQLAlchemy 2.0 Declarative Base and foundational migration entity.
"""

from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Optional
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


class SecurityEventSeverity(str, Enum):
    """
    Controlled severity classifications for enterprise security events.
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SecurityEventStatus(str, Enum):
    """
    Controlled action/disposition status for security events.
    """
    BLOCKED = "blocked"
    DETECTED = "detected"
    LOGGED = "logged"
    RESOLVED = "resolved"


class SecurityEventType(str, Enum):
    """
    Controlled taxonomy of VoiceLock security incident events.
    Deliberately separated from routine biometric verification outcomes.
    """
    # Rate Limiting & DoS
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    PAYLOAD_TOO_LARGE = "payload_too_large"

    # Terminal & Hardware Cryptography
    HMAC_NONCE_REPLAY = "hmac_nonce_replay"
    HMAC_SIGNATURE_INVALID = "hmac_signature_invalid"
    HMAC_TIMESTAMP_SKEW = "hmac_timestamp_skew"
    UNKNOWN_DEVICE_REJECTED = "unknown_device_rejected"
    REVOKED_DEVICE_BLOCKED = "revoked_device_blocked"
    DEVICE_KEY_INVALID = "device_key_invalid"

    # Authentication & Access Control
    AUTH_TOKEN_EXPIRED = "auth_token_expired"
    AUTH_TOKEN_REVOKED = "auth_token_revoked"
    AUTH_TOKEN_INVALID = "auth_token_invalid"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    UNAUTHORIZED_SPEAKER_CLAIM = "unauthorized_speaker_claim"

    # System & Administrative
    ADMIN_ACTION = "admin_action"
    SUSPICIOUS_PAYLOAD = "suspicious_payload"


VALID_SECURITY_EVENT_SEVERITIES = frozenset(item.value for item in SecurityEventSeverity)
VALID_SECURITY_EVENT_STATUSES = frozenset(item.value for item in SecurityEventStatus)
VALID_SECURITY_EVENT_TYPES = frozenset(item.value for item in SecurityEventType)

FORBIDDEN_SECURITY_METADATA_KEYS = frozenset({
    "token", "authorization", "password", "secret", "secret_hash",
    "key", "hmac_key", "signature", "audio", "embedding",
    "similarity", "similarity_score", "ip", "client_ip", "user_agent",
})


class SecurityEvent(Base):
    """
    Durable security event audit journal entity.
    Records enterprise security incidents, cryptographic anomalies,
    access control violations, and administrative actions without persisting
    raw audio, biometric embeddings, similarity scores, or credentials.

    Privacy & Security Architecture:
    1. Separation of Concerns: Routine biometric match results and verification
       outcomes are recorded in VerificationEvent. SecurityEvent does NOT duplicate
       or store standard verification outcomes.
    2. Strict Data Minimization: Raw audio, biometric embeddings, similarity scores,
       bearer tokens, passwords, HMAC keys, and raw exception stack traces are
       strictly excluded from persistence.
    3. Privacy Safeguard: IP addresses and user-agent strings are excluded by default
       to prevent unnecessary tracking and PII accumulation.
    4. Audit History Preservation: When an associated registered device is deleted,
       the security event is retained with device_id set to NULL (ondelete="SET NULL").
       user_id is an external identity string (Firebase UID) with no cascading delete.
    5. Bounded Metadata: Metadata is optional, bounded to <=2048 characters, and
       restricted to safe structured JSON keys. Prohibits arbitrary data sinks.
    6. Non-Repudiation Boundary: This table provides durable enterprise audit logging;
       it does not claim hardware-backed tamper-proof or cryptographic non-repudiation.
    """
    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    severity: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="blocked",
    )
    details: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(128),
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
    metadata_json: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_security_events_severity",
        ),
        CheckConstraint(
            "status IN ('blocked', 'detected', 'logged', 'resolved')",
            name="ck_security_events_status",
        ),
        CheckConstraint(
            "event_type IN ("
            "'rate_limit_exceeded', 'payload_too_large', 'hmac_nonce_replay', "
            "'hmac_signature_invalid', 'hmac_timestamp_skew', 'unknown_device_rejected', "
            "'revoked_device_blocked', 'device_key_invalid', 'auth_token_expired', "
            "'auth_token_revoked', 'auth_token_invalid', 'unauthorized_access', "
            "'unauthorized_speaker_claim', 'admin_action', 'suspicious_payload'"
            ")",
            name="ck_security_events_event_type",
        ),
        Index("ix_security_events_created_severity", "created_at", "severity"),
        Index("ix_security_events_created_type", "created_at", "event_type"),
    )

    # ORM relationship for device navigation
    device: Mapped[Optional["DeviceRecord"]] = relationship(
        "DeviceRecord",
        backref="security_events",
        passive_deletes=True,
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("status", "blocked")
        if "created_at" not in kwargs or kwargs["created_at"] is None:
            kwargs["created_at"] = datetime.now(timezone.utc)
        super().__init__(**kwargs)

    @validates("created_at")
    def validate_created_at(self, key: str, value: Any) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if not isinstance(value, datetime):
            raise ValueError("created_at must be a datetime object.")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    @validates("event_type")
    def validate_event_type(self, key: str, value: str) -> str:
        if not value or value not in VALID_SECURITY_EVENT_TYPES:
            raise ValueError(
                f"Invalid security event_type '{value}'. Must be one of {sorted(VALID_SECURITY_EVENT_TYPES)}."
            )
        return value

    @validates("severity")
    def validate_severity(self, key: str, value: str) -> str:
        if not value or value not in VALID_SECURITY_EVENT_SEVERITIES:
            raise ValueError(
                f"Invalid security severity '{value}'. Must be one of {sorted(VALID_SECURITY_EVENT_SEVERITIES)}."
            )
        return value

    @validates("status")
    def validate_status(self, key: str, value: str) -> str:
        if not value or value not in VALID_SECURITY_EVENT_STATUSES:
            raise ValueError(
                f"Invalid security status '{value}'. Must be one of {sorted(VALID_SECURITY_EVENT_STATUSES)}."
            )
        return value

    @validates("details")
    def validate_details(self, key: str, value: Optional[str]) -> Optional[str]:
        if value is not None and len(value) > 255:
            raise ValueError("details must not exceed 255 characters.")
        return value

    @validates("user_id")
    def validate_user_id(self, key: str, value: Optional[str]) -> Optional[str]:
        if value is not None and len(value) > 128:
            raise ValueError("user_id must not exceed 128 characters.")
        return value

    @validates("device_id")
    def validate_device_id(self, key: str, value: Optional[str]) -> Optional[str]:
        if value is not None and len(value) > 64:
            raise ValueError("device_id must not exceed 64 characters.")
        return value

    @validates("request_id")
    def validate_request_id(self, key: str, value: Optional[str]) -> Optional[str]:
        if value is not None and len(value) > 64:
            raise ValueError("request_id must not exceed 64 characters.")
        return value

    @validates("metadata_json")
    def validate_metadata_json(self, key: str, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, dict):
            lowered_keys = {str(k).lower() for k in value.keys()}
            prohibited = lowered_keys & FORBIDDEN_SECURITY_METADATA_KEYS
            if prohibited:
                raise ValueError(f"metadata_json contains prohibited sensitive key(s): {sorted(prohibited)}")
            serialized = json.dumps(value)
            if len(serialized) > 2048:
                raise ValueError("metadata_json must not exceed 2048 characters.")
            return serialized

        if not isinstance(value, str):
            raise ValueError("metadata_json must be a JSON string or dict.")
        if len(value) > 2048:
            raise ValueError("metadata_json must not exceed 2048 characters.")
        try:
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ValueError("metadata_json must represent a JSON object.")
        except json.JSONDecodeError as exc:
            raise ValueError(f"metadata_json must be valid JSON: {exc}")

        lowered_keys = {str(k).lower() for k in parsed.keys()}
        prohibited = lowered_keys & FORBIDDEN_SECURITY_METADATA_KEYS
        if prohibited:
            raise ValueError(f"metadata_json contains prohibited sensitive key(s): {sorted(prohibited)}")
        return value




