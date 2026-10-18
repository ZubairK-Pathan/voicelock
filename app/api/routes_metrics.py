"""
app/api/routes_metrics.py — Aggregate biometric verification metrics and telemetry endpoint.

Restricted strictly to administrators.
Aggregates data exclusively via VerificationEventRepository.
Exposes zero PII, event IDs, speaker IDs, device IDs, audio, or biometric vectors.
"""

from datetime import datetime, timezone
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedUser, get_current_admin
from app.db.base import VALID_VERIFICATION_FLOWS
from app.db.session import get_db
from app.repositories.verification_event_repository import VerificationEventRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Metrics"])


def compute_success_rate(verified: int, rejected: int, challenge_failed: int) -> float:
    """
    Compute biometric verification success percentage.
    
    Denominator: verified + rejected + challenge_failed (all biometric/liveness evaluations).
    Processing errors (error) are excluded because they represent system/media transport faults
    rather than biometric rejection decisions.
    
    Returns 0.0 when the denominator is zero.
    """
    denominator = verified + rejected + challenge_failed
    if denominator <= 0:
        return 0.0
    return round((verified / denominator) * 100.0, 2)


class VerificationMetricsResponse(BaseModel):
    """
    Aggregate verification telemetry metrics.
    Strictly aggregates only — zero individual events, user IDs, speaker IDs, device IDs,
    timestamps for individual attempts, or biometric vectors exposed.
    """
    total: int = Field(..., description="Total count of recorded verification events matching filters")
    verified: int = Field(..., description="Count of accepted biometric verifications")
    rejected: int = Field(..., description="Count of rejected biometric matches")
    challenge_failed: int = Field(..., description="Count of liveness challenge failures")
    error: int = Field(..., description="Count of processing or runtime errors")
    success_rate: float = Field(
        ...,
        description=(
            "Biometric success percentage: verified / (verified + rejected + challenge_failed) * 100. "
            "Excludes processing errors from the denominator to reflect true biometric decision quality. "
            "Returns 0.0 when denominator is zero."
        ),
    )
    start_time: Optional[datetime] = Field(None, description="Start timestamp filter (inclusive, UTC)")
    end_time: Optional[datetime] = Field(None, description="End timestamp filter (exclusive, UTC)")
    verification_flow: Optional[str] = Field(None, description="Verification flow filter ('web', 'device', or null)")


@router.get("/metrics/verification", response_model=VerificationMetricsResponse)
@router.get("/metrics", response_model=VerificationMetricsResponse)
def get_verification_metrics(
    start_time: Optional[datetime] = Query(None, description="Start of time window (ISO 8601, UTC, inclusive)"),
    end_time: Optional[datetime] = Query(None, description="End of time window (ISO 8601, UTC, exclusive)"),
    verification_flow: Optional[str] = Query(None, description="Verification flow filter: 'web' or 'device'"),
    admin: AuthenticatedUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Retrieve aggregate biometric verification metrics from persistent VerificationEvent records.
    Restricted strictly to administrators with active, non-revoked session.
    
    Data Minimization Guarantee:
    Exposes only aggregate counts and percentages. Never leaks raw event rows, individual attempt
    timestamps, user IDs, speaker IDs, device IDs, request IDs, audio files, or biometric embeddings.
    """
    # 1. Normalize time window to UTC
    norm_start = start_time.replace(tzinfo=timezone.utc) if start_time and start_time.tzinfo is None else start_time
    norm_end = end_time.replace(tzinfo=timezone.utc) if end_time and end_time.tzinfo is None else end_time

    if norm_start is not None and norm_end is not None and norm_start > norm_end:
        raise HTTPException(
            status_code=400,
            detail="start_time cannot be greater than end_time.",
        )

    # 2. Validate verification flow filter if supplied
    clean_flow = None
    if verification_flow is not None:
        clean_flow = str(verification_flow).strip()
        if clean_flow not in VALID_VERIFICATION_FLOWS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid verification_flow '{clean_flow}'. Must be one of {sorted(VALID_VERIFICATION_FLOWS)}.",
            )

    # 3. Retrieve aggregates from repository
    repo = VerificationEventRepository(db)
    try:
        counts = repo.count_by_outcome(
            start_time=norm_start,
            end_time=norm_end,
            verification_flow=clean_flow,
        )
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as exc:
        logger.exception("Database failure while retrieving verification metrics: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Database failure while retrieving verification metrics.",
        ) from exc

    v_count = counts.get("verified", 0)
    r_count = counts.get("rejected", 0)
    cf_count = counts.get("challenge_failed", 0)
    err_count = counts.get("error", 0)
    total = sum(counts.values())

    success_rate = compute_success_rate(
        verified=v_count,
        rejected=r_count,
        challenge_failed=cf_count,
    )

    return VerificationMetricsResponse(
        total=total,
        verified=v_count,
        rejected=r_count,
        challenge_failed=cf_count,
        error=err_count,
        success_rate=success_rate,
        start_time=norm_start,
        end_time=norm_end,
        verification_flow=clean_flow,
    )
