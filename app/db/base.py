"""
app/db/base.py — SQLAlchemy 2.0 Declarative Base and foundational migration entity.
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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

