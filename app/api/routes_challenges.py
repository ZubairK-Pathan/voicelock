"""
app/api/routes_challenges.py — Stateful liveness challenge generation endpoint.
"""

import sys
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request

from app.schemas.challenge import ChallengeResponse
from app.services.challenge_service import challenge_display
import app.services.challenge_service as challenge_service
import app.services.speaker_service as speaker_service
from app.core.config import DEFAULT_CHALLENGE_TTL_SECONDS, DEFAULT_CHALLENGE_LENGTH
from app.core.auth import AuthenticatedUser, get_current_user

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


@router.post("/challenge", response_model=ChallengeResponse)
async def create_challenge(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Generate an unpredictable, cryptographically secure 3-digit liveness challenge.
    Binds the challenge to a verification session and optionally to a claimed identity.
    Requires authenticated web user or administrator.
    Expires in 60 seconds.
    """
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
        except Exception:
            pass
    else:
        try:
            form = await request.form()
            claimed_identity = form.get("claimed_identity")
            session_id = form.get("session_id")
        except Exception:
            pass

    get_sys = _get_system()
    profiles, _ = get_sys()
    if claimed_identity is not None:
        clean_claimed = str(claimed_identity).strip()
        if profiles and clean_claimed not in profiles:
            raise HTTPException(
                status_code=404,
                detail=f"Speaker '{clean_claimed}' is not registered."
            )
        claimed_identity = clean_claimed

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
