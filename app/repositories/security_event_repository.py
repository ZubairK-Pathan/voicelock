"""
app/repositories/security_event_repository.py — Data access repository for SecurityEvent entities.
Encapsulates database queries, filtering, and bounded cursor-based pagination using SQLAlchemy 2.0.

Architectural Guarantees:
1. Bounded Queries: Enforces strict upper limit (MAX_LIMIT = 100) on page sizes.
2. Deterministic Cursor Pagination: Uses (created_at DESC, id DESC) with tie-breaker logic to eliminate
   duplicate or skipped events across page boundaries even when multiple records share identical timestamps.
3. Database Filtering: All filters (event_type, severity, status, time windows, actors, devices) are applied
   at the database level via SQL WHERE clauses rather than in-memory Python filtering.
4. Privacy & Isolation: Does not commit or roll back caller transactions; flushes when creating records.
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.base import (
    SecurityEvent,
    VALID_SECURITY_EVENT_TYPES,
    VALID_SECURITY_EVENT_SEVERITIES,
    VALID_SECURITY_EVENT_STATUSES,
)
from app.schemas.security_event import decode_cursor, encode_cursor


class SecurityEventRepositoryError(Exception):
    """Base exception for security event repository operations."""
    pass


class InvalidCursorError(SecurityEventRepositoryError, ValueError):
    """Raised when a pagination cursor cannot be decoded or is invalid."""
    pass


class SecurityEventRepository:
    """
    SQLAlchemy 2.0 repository managing persistence and queries for SecurityEvent audit records.
    """

    DEFAULT_LIMIT = 50
    MAX_LIMIT = 100

    def __init__(self, session: Session):
        if session is None:
            raise ValueError("SecurityEventRepository requires an active SQLAlchemy Session.")
        self.session = session

    def list_events(
        self,
        limit: int = DEFAULT_LIMIT,
        cursor: Optional[str] = None,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        user_id: Optional[str] = None,
        device_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Tuple[List[SecurityEvent], Optional[str], bool]:
        """
        Query security audit events with database-level filtering and deterministic cursor pagination.

        Returns:
            Tuple of (records_in_page, next_cursor, has_more)
        """
        # 1. Validate page limit bounds
        if limit < 1:
            raise ValueError("limit must be greater than or equal to 1.")
        if limit > self.MAX_LIMIT:
            raise ValueError(f"limit exceeds maximum permitted page size of {self.MAX_LIMIT}.")

        stmt = select(SecurityEvent)

        # 2. Apply filters
        if event_type is not None:
            clean_type = event_type.strip()
            if clean_type not in VALID_SECURITY_EVENT_TYPES:
                raise ValueError(
                    f"Invalid event_type '{clean_type}'. Must be one of {sorted(VALID_SECURITY_EVENT_TYPES)}."
                )
            stmt = stmt.where(SecurityEvent.event_type == clean_type)

        if severity is not None:
            clean_sev = severity.strip().lower()
            if clean_sev not in VALID_SECURITY_EVENT_SEVERITIES:
                raise ValueError(
                    f"Invalid severity '{clean_sev}'. Must be one of {sorted(VALID_SECURITY_EVENT_SEVERITIES)}."
                )
            stmt = stmt.where(SecurityEvent.severity == clean_sev)

        if status is not None:
            clean_status = status.strip().lower()
            if clean_status not in VALID_SECURITY_EVENT_STATUSES:
                raise ValueError(
                    f"Invalid status '{clean_status}'. Must be one of {sorted(VALID_SECURITY_EVENT_STATUSES)}."
                )
            stmt = stmt.where(SecurityEvent.status == clean_status)

        if user_id is not None:
            stmt = stmt.where(SecurityEvent.user_id == user_id.strip())

        if device_id is not None:
            stmt = stmt.where(SecurityEvent.device_id == device_id.strip())

        if request_id is not None:
            stmt = stmt.where(SecurityEvent.request_id == request_id.strip())

        # Time-window filters: [start_time, end_time)
        norm_start = start_time if (start_time is None or start_time.tzinfo is not None) else start_time.replace(tzinfo=timezone.utc)
        norm_end = end_time if (end_time is None or end_time.tzinfo is not None) else end_time.replace(tzinfo=timezone.utc)

        if norm_start is not None and norm_end is not None and norm_start > norm_end:
            raise ValueError("start_time cannot be greater than end_time.")

        if norm_start is not None:
            stmt = stmt.where(SecurityEvent.created_at >= norm_start)
        if norm_end is not None:
            stmt = stmt.where(SecurityEvent.created_at < norm_end)

        # 3. Apply cursor filter if continuation cursor provided
        if cursor is not None:
            try:
                cursor_time, cursor_id = decode_cursor(cursor)
            except ValueError as exc:
                raise InvalidCursorError(f"Invalid pagination cursor: {exc}") from exc

            # Stable tie-breaker ordering (created_at DESC, id DESC):
            # Record is strictly after cursor if created_at < cursor_time OR (created_at == cursor_time AND id < cursor_id)
            cursor_condition = or_(
                SecurityEvent.created_at < cursor_time,
                and_(
                    SecurityEvent.created_at == cursor_time,
                    SecurityEvent.id < cursor_id,
                ),
            )
            stmt = stmt.where(cursor_condition)

        # 4. Deterministic ordering: newest first with integer ID tie-breaker
        stmt = stmt.order_by(SecurityEvent.created_at.desc(), SecurityEvent.id.desc())

        # 5. Fetch limit + 1 to determine if next page exists without full table count
        stmt = stmt.limit(limit + 1)
        results = list(self.session.scalars(stmt).all())

        has_more = len(results) > limit
        if has_more:
            page_records = results[:limit]
            last_item = page_records[-1]
            next_cursor = encode_cursor(last_item.created_at, last_item.id)
        else:
            page_records = results
            next_cursor = None

        return page_records, next_cursor, has_more

    def get_event(self, event_id: int) -> Optional[SecurityEvent]:
        """
        Retrieve a single SecurityEvent by integer primary key ID.
        """
        if event_id is None or event_id <= 0:
            return None
        stmt = select(SecurityEvent).where(SecurityEvent.id == event_id)
        return self.session.scalar(stmt)
