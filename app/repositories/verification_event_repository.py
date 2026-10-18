"""
app/repositories/verification_event_repository.py — Data access repository for VerificationEvent entities.
Encapsulates database persistence, retrieval, windowed filtering, and aggregate queries for biometric
verification audit records using SQLAlchemy 2.0.

Architectural & Security Guarantees:
1. Caller-Controlled Transactions: Repository methods never commit or roll back the caller's transaction.
   They flush to populate generated primary keys and verify database constraints.
2. Zero Biometric & Credential Persistence: Strictly excludes audio data, audio file paths,
   192-dimensional embeddings, similarity scores, passwords, bearer tokens, and device secrets.
3. Interval Semantics: Time window filtering strictly adheres to [start_time, end_time)
   (start inclusive, end exclusive) in UTC.
4. Bounded Queries: Pagination enforces upper limits to prevent memory exhaustion and unbounded table scans.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Union
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import (
    VerificationEvent,
    VerificationOutcome,
    VALID_VERIFICATION_OUTCOMES,
    VALID_VERIFICATION_FLOWS,
)


class VerificationEventRepositoryError(Exception):
    """Base exception for verification event repository errors."""
    pass


class VerificationEventNotFoundError(VerificationEventRepositoryError, KeyError):
    """Raised when a requested verification event is not found."""
    pass


class VerificationEventRepository:
    """
    SQLAlchemy 2.0 repository managing persistence and queries for VerificationEvent.
    Methods operate within the caller's Session and perform flushes where needed,
    leaving transaction commit and rollback control to the caller.
    """

    DEFAULT_LIMIT = 50
    MAX_LIMIT = 500

    def __init__(self, session: Session):
        if session is None:
            raise ValueError("VerificationEventRepository requires an active SQLAlchemy Session.")
        self.session = session

    def create_event(
        self,
        outcome: Union[str, VerificationOutcome],
        verification_flow: str = "web",
        user_id: Optional[str] = None,
        speaker_id: Optional[str] = None,
        device_id: Optional[str] = None,
        request_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> VerificationEvent:
        """
        Create and persist a new VerificationEvent in the database session.
        Flushes to the database transaction to populate autoincrement ID and verify constraints.
        Does NOT commit or roll back the transaction.
        """
        clean_outcome = outcome.value if isinstance(outcome, VerificationOutcome) else str(outcome).strip() if outcome else ""
        if clean_outcome not in VALID_VERIFICATION_OUTCOMES:
            raise ValueError(
                f"Invalid outcome '{clean_outcome}'. Must be one of {sorted(VALID_VERIFICATION_OUTCOMES)}."
            )

        clean_flow = str(verification_flow).strip() if verification_flow else ""
        if clean_flow not in VALID_VERIFICATION_FLOWS:
            raise ValueError(
                f"Invalid verification_flow '{clean_flow}'. Must be one of {sorted(VALID_VERIFICATION_FLOWS)}."
            )

        clean_user_id = user_id.strip() if user_id and user_id.strip() else None
        clean_speaker_id = speaker_id.strip() if speaker_id and speaker_id.strip() else None
        clean_device_id = device_id.strip() if device_id and device_id.strip() else None
        clean_request_id = request_id.strip() if request_id and request_id.strip() else None

        if created_at is not None:
            event_created_at = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=timezone.utc)
        else:
            event_created_at = datetime.now(timezone.utc)

        record = VerificationEvent(
            outcome=clean_outcome,
            verification_flow=clean_flow,
            user_id=clean_user_id,
            speaker_id=clean_speaker_id,
            device_id=clean_device_id,
            request_id=clean_request_id,
            created_at=event_created_at,
        )

        self.session.add(record)
        self.session.flush()
        return record

    def get_event(self, event_id: int) -> Optional[VerificationEvent]:
        """
        Retrieve a single VerificationEvent by integer primary key ID.
        Returns None if not found.
        """
        if event_id is None or event_id <= 0:
            return None
        stmt = select(VerificationEvent).where(VerificationEvent.id == event_id)
        return self.session.scalar(stmt)

    def get_or_raise(self, event_id: int) -> VerificationEvent:
        """
        Retrieve a VerificationEvent by ID or raise VerificationEventNotFoundError.
        """
        event = self.get_event(event_id)
        if event is None:
            raise VerificationEventNotFoundError(f"Verification event with ID {event_id} not found.")
        return event

    def list_events(
        self,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        outcome: Optional[Union[str, VerificationOutcome]] = None,
        verification_flow: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        user_id: Optional[str] = None,
        speaker_id: Optional[str] = None,
        device_id: Optional[str] = None,
    ) -> List[VerificationEvent]:
        """
        List verification events with bounded pagination, deterministic ordering,
        and optional outcome, flow, identity, and time-window filtering.
        Time window filtering adheres strictly to [start_time, end_time) in UTC.
        Ordering: newest first (created_at DESC, id DESC).
        """
        if limit < 1 or limit > self.MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {self.MAX_LIMIT}.")
        if offset < 0:
            raise ValueError("offset must be non-negative.")

        stmt = select(VerificationEvent)

        # Outcome filtering
        if outcome is not None:
            clean_outcome = outcome.value if isinstance(outcome, VerificationOutcome) else str(outcome).strip()
            if clean_outcome not in VALID_VERIFICATION_OUTCOMES:
                raise ValueError(
                    f"Invalid outcome '{clean_outcome}'. Must be one of {sorted(VALID_VERIFICATION_OUTCOMES)}."
                )
            stmt = stmt.where(VerificationEvent.outcome == clean_outcome)

        # Flow filtering
        if verification_flow is not None:
            clean_flow = str(verification_flow).strip()
            if clean_flow not in VALID_VERIFICATION_FLOWS:
                raise ValueError(
                    f"Invalid verification_flow '{clean_flow}'. Must be one of {sorted(VALID_VERIFICATION_FLOWS)}."
                )
            stmt = stmt.where(VerificationEvent.verification_flow == clean_flow)

        # Identity filters
        if user_id is not None:
            stmt = stmt.where(VerificationEvent.user_id == user_id.strip())
        if speaker_id is not None:
            stmt = stmt.where(VerificationEvent.speaker_id == speaker_id.strip())
        if device_id is not None:
            stmt = stmt.where(VerificationEvent.device_id == device_id.strip())

        # Time-window filtering [start_time, end_time)
        norm_start = start_time if (start_time is None or start_time.tzinfo is not None) else start_time.replace(tzinfo=timezone.utc)
        norm_end = end_time if (end_time is None or end_time.tzinfo is not None) else end_time.replace(tzinfo=timezone.utc)

        if norm_start is not None and norm_end is not None and norm_start > norm_end:
            raise ValueError("start_time cannot be greater than end_time.")

        if norm_start is not None:
            stmt = stmt.where(VerificationEvent.created_at >= norm_start)
        if norm_end is not None:
            stmt = stmt.where(VerificationEvent.created_at < norm_end)

        # Deterministic ordering: newest first with unique tie-breaker
        stmt = stmt.order_by(VerificationEvent.created_at.desc(), VerificationEvent.id.desc())
        stmt = stmt.limit(limit).offset(offset)

        return list(self.session.scalars(stmt).all())

    def count_events(
        self,
        outcome: Optional[Union[str, VerificationOutcome]] = None,
        verification_flow: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        user_id: Optional[str] = None,
        speaker_id: Optional[str] = None,
        device_id: Optional[str] = None,
    ) -> int:
        """
        Count verification events matching optional filters using database aggregates.
        Time window filtering adheres strictly to [start_time, end_time) in UTC.
        """
        stmt = select(func.count(VerificationEvent.id))

        if outcome is not None:
            clean_outcome = outcome.value if isinstance(outcome, VerificationOutcome) else str(outcome).strip()
            if clean_outcome not in VALID_VERIFICATION_OUTCOMES:
                raise ValueError(
                    f"Invalid outcome '{clean_outcome}'. Must be one of {sorted(VALID_VERIFICATION_OUTCOMES)}."
                )
            stmt = stmt.where(VerificationEvent.outcome == clean_outcome)

        if verification_flow is not None:
            clean_flow = str(verification_flow).strip()
            if clean_flow not in VALID_VERIFICATION_FLOWS:
                raise ValueError(
                    f"Invalid verification_flow '{clean_flow}'. Must be one of {sorted(VALID_VERIFICATION_FLOWS)}."
                )
            stmt = stmt.where(VerificationEvent.verification_flow == clean_flow)

        if user_id is not None:
            stmt = stmt.where(VerificationEvent.user_id == user_id.strip())
        if speaker_id is not None:
            stmt = stmt.where(VerificationEvent.speaker_id == speaker_id.strip())
        if device_id is not None:
            stmt = stmt.where(VerificationEvent.device_id == device_id.strip())

        norm_start = start_time if (start_time is None or start_time.tzinfo is not None) else start_time.replace(tzinfo=timezone.utc)
        norm_end = end_time if (end_time is None or end_time.tzinfo is not None) else end_time.replace(tzinfo=timezone.utc)

        if norm_start is not None and norm_end is not None and norm_start > norm_end:
            raise ValueError("start_time cannot be greater than end_time.")

        if norm_start is not None:
            stmt = stmt.where(VerificationEvent.created_at >= norm_start)
        if norm_end is not None:
            stmt = stmt.where(VerificationEvent.created_at < norm_end)

        count_val = self.session.scalar(stmt)
        return int(count_val or 0)

    def count_by_outcome(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        verification_flow: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        Return aggregate counts grouped by outcome category over an optional [start, end) time window.
        Guarantees all valid outcomes are represented in the returned dictionary with a count of at least 0.
        """
        norm_start = start_time if (start_time is None or start_time.tzinfo is not None) else start_time.replace(tzinfo=timezone.utc)
        norm_end = end_time if (end_time is None or end_time.tzinfo is not None) else end_time.replace(tzinfo=timezone.utc)

        if norm_start is not None and norm_end is not None and norm_start > norm_end:
            raise ValueError("start_time cannot be greater than end_time.")

        # Initialize full dictionary of all valid outcomes
        result = {outcome: 0 for outcome in sorted(VALID_VERIFICATION_OUTCOMES)}

        stmt = select(VerificationEvent.outcome, func.count(VerificationEvent.id)).group_by(VerificationEvent.outcome)

        if verification_flow is not None:
            clean_flow = str(verification_flow).strip()
            if clean_flow not in VALID_VERIFICATION_FLOWS:
                raise ValueError(
                    f"Invalid verification_flow '{clean_flow}'. Must be one of {sorted(VALID_VERIFICATION_FLOWS)}."
                )
            stmt = stmt.where(VerificationEvent.verification_flow == clean_flow)

        if norm_start is not None:
            stmt = stmt.where(VerificationEvent.created_at >= norm_start)
        if norm_end is not None:
            stmt = stmt.where(VerificationEvent.created_at < norm_end)

        for outcome_key, count_val in self.session.execute(stmt):
            if outcome_key in result:
                result[outcome_key] = count_val

        return result
