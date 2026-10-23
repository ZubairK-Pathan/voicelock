"""
app/api/routes_security_events.py — Administrator Security Audit Events API.

Secured strictly with Firebase token verification and get_current_admin authorization (RBAC).
Never trusts client-supplied admin flags or query parameters.
Data minimization: Biometric embeddings, raw audio, credentials, and sensitive metadata are strictly excluded.
Pagination: Bounded, deterministic cursor-based pagination with unique sequence tie-breaker.
"""

from datetime import datetime, timezone
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from starlette import status as http_status
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedUser, get_current_admin
from app.db.session import get_db
from app.repositories.security_event_repository import (
    SecurityEventRepository,
    InvalidCursorError,
)
from app.schemas.security_event import (
    SecurityEventItem,
    SecurityEventsResponse,
    sanitize_event_metadata,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/admin/security-events", tags=["Security Audit Events"])


def _parse_iso_datetime(val: Optional[str], param_name: str) -> Optional[datetime]:
    """
    Safely parse ISO 8601 datetime query parameters, handling UTC offsets and URL space decoding.
    """
    if val is None:
        return None
    clean = str(val).strip()
    if not clean:
        return None

    # Handle space decoded from '+' in application/x-www-form-urlencoded
    if " " in clean and "+" not in clean:
        clean = clean.replace(" ", "+")
    if clean.endswith("Z") or clean.endswith("z"):
        clean = clean[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {param_name} format. Expected valid ISO 8601 timestamp: {exc}",
        ) from exc


@router.get("", response_model=SecurityEventsResponse)
@router.get("/", response_model=SecurityEventsResponse, include_in_schema=False)
def list_security_events(
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
        description="Number of security events to return per page (1 to 100, default 50)",
    ),
    cursor: Optional[str] = Query(
        default=None,
        description="Continuation token for retrieving the next page of audit events",
    ),
    event_type: Optional[str] = Query(
        default=None,
        description="Filter by classified security incident or event type",
    ),
    severity: Optional[str] = Query(
        default=None,
        description="Filter by severity level: low, medium, high, critical",
    ),
    status: Optional[str] = Query(
        default=None,
        description="Filter by disposition status: blocked, detected, logged, resolved",
    ),
    start_time: Optional[str] = Query(
        default=None,
        description="Lower bound timestamp for event creation in ISO 8601 format (inclusive, UTC)",
    ),
    end_time: Optional[str] = Query(
        default=None,
        description="Upper bound timestamp for event creation in ISO 8601 format (exclusive, UTC)",
    ),
    user_id: Optional[str] = Query(
        default=None,
        description="Filter by actor Firebase UID",
    ),
    device_id: Optional[str] = Query(
        default=None,
        description="Filter by physical terminal hardware device ID",
    ),
    request_id: Optional[str] = Query(
        default=None,
        description="Filter by request correlation trace identifier",
    ),
    admin: AuthenticatedUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    List durable security audit events with bounded, deterministic cursor pagination.
    Restricted strictly to administrators with a verified non-revoked session.
    """
    # Parse and validate optional datetime parameters
    parsed_start = _parse_iso_datetime(start_time, "start_time")
    parsed_end = _parse_iso_datetime(end_time, "end_time")

    if parsed_start is not None and parsed_end is not None and parsed_start > parsed_end:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="start_time cannot be greater than end_time.",
        )

    repo = SecurityEventRepository(db)

    try:
        records, next_cursor, has_more = repo.list_events(
            limit=limit,
            cursor=cursor,
            event_type=event_type,
            severity=severity,
            status=status,
            start_time=parsed_start,
            end_time=parsed_end,
            user_id=user_id,
            device_id=device_id,
            request_id=request_id,
        )
    except InvalidCursorError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid pagination cursor: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("Database failure while querying security events: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database failure while querying security audit events.",
        ) from exc

    # Sanitize metadata and construct clean Pydantic response models
    items = [
        SecurityEventItem(
            id=rec.id,
            created_at=rec.created_at,
            event_type=rec.event_type,
            severity=rec.severity,
            status=rec.status,
            details=rec.details,
            user_id=rec.user_id,
            device_id=rec.device_id,
            request_id=rec.request_id,
            metadata=sanitize_event_metadata(rec.metadata_json),
        )
        for rec in records
    ]

    return SecurityEventsResponse(
        events=items,
        next_cursor=next_cursor,
        has_more=has_more,
        count=len(items),
    )
