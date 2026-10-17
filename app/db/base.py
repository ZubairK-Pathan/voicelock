"""
app/db/base.py — SQLAlchemy 2.0 Declarative Base and foundational migration entity.
"""

from datetime import datetime, timezone
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
    description: Mapped[str] = mapped_column(Text, nullable=True)
