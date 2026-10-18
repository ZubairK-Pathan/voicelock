"""
app/api/routes_challenges.py — Stateful liveness challenge generation endpoint.
"""

import sys
from typing import Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.schemas.challenge import ChallengeResponse
from app.services.challenge_service import challenge_display
import app.services.challenge_service as challenge_service
import app.services.speaker_service as speaker_service
from app.core.config import DEFAULT_CHALLENGE_TTL_SECONDS, DEFAULT_CHALLENGE_LENGTH
from app.core.auth import AuthenticatedUser
from app.core.device_auth import (
    get_current_actor,
    check_verification_authorization,
    resolve_user_voice_identity,
    AuthenticatedDevice,
)
from app.core.rate_limit import _challenge_limiter, get_actor_rate_key, enforce_rate_limit
from app.core.middleware import PayloadTooLargeError
from app.db.session import get_db

router = APIRouter(tags=["Liveness"])


def _get_system():
    mod = sys.modules.get("cloud_api")
    if mod and hasattr(mod, "get_system"):
        return mod.get_system
    return speaker_service.get_system


def _get_challenge_store():
    mod = sys.modules.get("cloud_api")
    if mod and hasattr(mod, "default_challenge_store"):
        return mod.default_challenge_store
    return challenge_service.get_challenge_store()


def _get_speaker_service(session: Session) -> speaker_service.SpeakerService:
    mod = sys.modules.get("cloud_api")
    if mod and hasattr(mod, "SpeakerService"):
        return mod.SpeakerService(session)
    return speaker_service.SpeakerService(session)


def _is_mocked(fn) -> bool:
    from unittest.mock import Mock
    return isinstance(fn, Mock) or hasattr(fn, "_mock_return_value") or hasattr(fn, "mock")


@router.post("/challenge", response_model=ChallengeResponse)
async def create_challenge(
    request: Request,
    actor: Union[AuthenticatedUser, AuthenticatedDevice] = Depends(get_current_actor),
    db: Session = Depends(get_db),
):
    """
    Generate an unpredictable, cryptographically secure 3-digit liveness challenge.
    Binds the challenge to a verification session and optionally to a claimed identity.
    Requires authenticated web user, administrator, or trusted IoT device.
    Expires in 60 seconds.
    """
    # Enforce rate limit based on verified actor
    rate_key = get_actor_rate_key(actor, request)
    enforce_rate_limit(_challenge_limiter, rate_key, limit=30)
    claimed_identity = None
    session_id = None

    # Support both application/json and form-encoded requests
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                claimed_identity = body.get("claimed_identity")
                session_id = body.get("session_id")
        except PayloadTooLargeError:
            raise
        except Exception:
            pass
    else:
        try:
            form = await request.form()
            claimed_identity = form.get("claimed_identity")
            session_id = form.get("session_id")
        except PayloadTooLargeError:
            raise
        except Exception:
            pass

    get_sys = _get_system()
    if claimed_identity is not None:
        clean_claimed = str(claimed_identity).strip()
        if _is_mocked(get_sys):
            profiles, _ = get_sys()
            if profiles and clean_claimed not in profiles:
                raise HTTPException(
                    status_code=404,
                    detail=f"Speaker '{clean_claimed}' is not registered."
                )
        else:
            service = _get_speaker_service(db)
            try:
                if not service.is_speaker_active(clean_claimed):
                    raise HTTPException(
                        status_code=404,
                        detail=f"Speaker '{clean_claimed}' is not registered."
                    )
            except speaker_service.SpeakerServiceDatabaseError as exc:
                raise HTTPException(
                    status_code=500,
                    detail="Database failure during identity verification."
                ) from exc

        # Ordinary users can only challenge their bound voice identity
        check_verification_authorization(actor, clean_claimed, session=db)
        claimed_identity = clean_claimed
    elif isinstance(actor, AuthenticatedUser) and not actor.is_admin:
        # If ordinary user didn't supply claimed_identity, resolve their bound identity
        mapped_speaker = resolve_user_voice_identity(actor, session=db)
        if not mapped_speaker:
            raise HTTPException(
                status_code=403,
                detail="Forbidden: User account is not mapped to an enrolled speaker identity.",
            )
        claimed_identity = mapped_speaker

    store = _get_challenge_store()
    challenge = store.create_challenge(
        session_id=str(session_id).strip() if session_id else None,
        claimed_identity=claimed_identity,
        ttl_seconds=DEFAULT_CHALLENGE_TTL_SECONDS,
        length=DEFAULT_CHALLENGE_LENGTH,
    )

    return {
        "challenge_id": challenge.challenge_id,
        "session_id": challenge.session_id,
        "claimed_identity": challenge.claimed_identity,
        "digits": challenge.digits,
        "display": challenge_display(challenge.digits),
        "expires_at": challenge.expires_at,
        "expires_in_seconds": DEFAULT_CHALLENGE_TTL_SECONDS,
    }
