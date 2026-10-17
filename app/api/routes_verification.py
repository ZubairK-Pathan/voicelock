"""
app/api/routes_verification.py — Biometric identification, verification, and streaming endpoints.
"""

import io
import os
import sys
import time
from pathlib import Path
from typing import Optional, Union

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import soundfile as sf
from sqlalchemy.orm import Session

from app.core.config import SERVER_THRESHOLD, MAX_AUDIO_SIZE_BYTES
from app.core.auth import AuthenticatedUser, get_current_user, get_current_admin, authenticate_ws_admin
from app.core.device_auth import get_current_actor, check_verification_authorization, AuthenticatedDevice
from app.db.session import get_db
from app.core.rate_limit import (
    _verify_limiter,
    _identify_limiter,
    get_actor_rate_key,
    enforce_rate_limit,
    acquire_inference_slot,
    release_inference_slot,
)
import app.services.speaker_service as speaker_service
import app.services.challenge_service as challenge_service
import app.services.verification_service as verification_service
import predict
import liveness

router = APIRouter(tags=["Biometrics"])


def _get_system():
    mod = sys.modules.get("cloud_api")
    if mod and hasattr(mod, "get_system"):
        return mod.get_system
    return speaker_service.get_system


def _get_save_upload():
    mod = sys.modules.get("cloud_api")
    if mod and hasattr(mod, "save_upload"):
        return mod.save_upload
    return verification_service.save_upload


def _get_predict_speaker():
    mod = sys.modules.get("cloud_api")
    if mod and hasattr(mod, "predict_speaker"):
        return mod.predict_speaker
    return predict.predict_speaker


def _get_verify_speaker():
    mod = sys.modules.get("cloud_api")
    if mod and hasattr(mod, "verify_speaker"):
        return mod.verify_speaker
    return predict.verify_speaker


def _get_run_liveness_check():
    mod = sys.modules.get("cloud_api")
    if mod and hasattr(mod, "run_liveness_check"):
        return mod.run_liveness_check
    return liveness.run_liveness_check


def _get_challenge_store():
    mod = sys.modules.get("cloud_api")
    if mod and hasattr(mod, "default_challenge_store"):
        return mod.default_challenge_store
    return challenge_service.get_challenge_store()


@router.post("/identify")
async def identify(
    request: Request,
    audio: UploadFile = File(..., description="WAV/MP3/M4A audio file"),
    threshold: Optional[float] = Form(None, description="Deprecated client threshold; server enforces calibrated threshold"),
    admin: AuthenticatedUser = Depends(get_current_admin),
):
    """
    Identify the speaker in an uploaded audio file (1-to-N matching).
    Enforces server-side threshold, bounded upload limits, rate limits, and ADMIN privileges.
    """
    rate_key = get_actor_rate_key(admin, request)
    enforce_rate_limit(_identify_limiter, rate_key, limit=15)

    get_sys = _get_system()
    profiles, classifier = get_sys()
    if not profiles:
        raise HTTPException(status_code=503, detail="No speaker profiles are enrolled in the system.")

    save_fn = _get_save_upload()
    tmp_path = save_fn(audio, request=request)
    await acquire_inference_slot()
    try:
        predict_fn = _get_predict_speaker()
        result = predict_fn(
            audio_path=str(tmp_path),
            threshold=SERVER_THRESHOLD,
            classifier=classifier,
            profiles=profiles,
            verbose=False,
        )
        return {
            "predicted_speaker": result["predicted_speaker"],
            "similarity": round(result["similarity"], 4),
            "is_unknown": result["is_unknown"],
            "all_scores": {k: round(v, 4) for k, v in result["all_scores"].items()},
            "threshold_used": SERVER_THRESHOLD,
        }
    except HTTPException:
        raise
    except (ValueError, sf.LibsndfileError) as err:
        raise HTTPException(status_code=400, detail=f"Invalid or unreadable audio content: {err}")
    except RuntimeError as re:
        err_msg = str(re).lower()
        if "ffmpeg" in err_msg or "conversion failed" in err_msg:
            raise HTTPException(status_code=400, detail="Invalid audio stream or unreadable format.")
        raise HTTPException(status_code=500, detail="Biometric identification inference failed.")
    except Exception:
        raise HTTPException(status_code=500, detail="Biometric identification inference failed.")
    finally:
        release_inference_slot()
        if tmp_path.exists():
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@router.post("/verify")
async def verify(
    request: Request,
    audio: UploadFile = File(..., description="WAV/MP3/M4A audio file containing spoken challenge digits"),
    claimed_identity: str = Form(..., description="Name of the speaker being claimed"),
    challenge_id: Optional[str] = Form(None, description="Active liveness challenge ID"),
    session_id: Optional[str] = Form(None, description="Active verification session ID"),
    threshold: Optional[float] = Form(None, description="Deprecated client threshold; server enforces calibrated threshold"),
    actor: Union[AuthenticatedUser, AuthenticatedDevice] = Depends(get_current_actor),
    db: Session = Depends(get_db),
):
    """
    Verify whether the audio matches the claimed speaker identity (1-to-1)
    AND satisfies the bound liveness challenge (anti-spoofing / anti-replay).
    Requires authenticated web user, administrator, or trusted IoT device.
    
    Security workflow:
    1. Validates registration of claimed identity.
    2. Enforces caller authorization (persistent database-backed UserSpeakerMapping).
    3. Enforces rate limits per verified actor.
    4. Enforces presence of challenge_id and session_id.
    5. Atomically consumes the challenge (Single-Attempt Invalidation) BEFORE audio processing.
    6. Evaluates spoken digits against expected challenge via offline Vosk STT.
    7. If liveness fails, access is DENIED immediately without running ML inference.
    8. If liveness passes, runs ECAPA-TDNN speaker verification under concurrency control.
    """
    rate_key = get_actor_rate_key(actor, request)
    enforce_rate_limit(_verify_limiter, rate_key, limit=30)
    get_sys = _get_system()
    profiles, classifier = get_sys()
    if not profiles:
        raise HTTPException(status_code=503, detail="No speaker profiles are enrolled in the system.")

    claimed_identity = claimed_identity.strip()
    if not claimed_identity or claimed_identity not in profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Speaker '{claimed_identity}' is not registered."
        )

    # Caller authorization: Ordinary users can only verify their bound voice identity
    check_verification_authorization(actor, claimed_identity, session=db)

    # 1. Challenge & Session binding validation
    if not challenge_id or not str(challenge_id).strip() or not session_id or not str(session_id).strip():
        raise HTTPException(
            status_code=400,
            detail="Missing required challenge_id or session_id for verification."
        )

    clean_challenge_id = str(challenge_id).strip()
    clean_session_id = str(session_id).strip()

    # 2. Atomically validate and consume challenge BEFORE processing audio upload.
    # Rejects invalid, expired, reused, or session-mismatched challenges early,
    # preventing unnecessary disk I/O and payload buffering.
    store = _get_challenge_store()
    valid, reason, challenge = store.validate_and_consume(
        challenge_id=clean_challenge_id,
        session_id=clean_session_id,
        claimed_identity=claimed_identity,
    )
    if not valid or challenge is None:
        raise HTTPException(status_code=400, detail=reason)

    # 3. Save upload and enforce upload limits
    tmp_path = None
    try:
        save_fn = _get_save_upload()
        tmp_path = save_fn(audio, request=request)

        # 4. Spoken liveness verification (Vosk STT challenge evaluation)
        liveness_fn = _get_run_liveness_check()
        is_live, liveness_reason, _ = liveness_fn(str(tmp_path), challenge.digits)
        if not is_live:
            # Liveness failure: Fail closed and deny access without running biometric inference
            return {
                "accepted": False,
                "action": "DENY",
                "claimed_identity": claimed_identity,
                "similarity": 0.0,
                "threshold_used": SERVER_THRESHOLD,
                "liveness_passed": False,
                "reason": f"Liveness check failed: {liveness_reason}",
            }

        # 5. Biometric speaker verification (SpeechBrain ECAPA-TDNN) under concurrency control
        await acquire_inference_slot()
        try:
            verify_fn = _get_verify_speaker()
            result = verify_fn(
                audio_path=str(tmp_path),
                claimed_identity=claimed_identity,
                threshold=SERVER_THRESHOLD,
                classifier=classifier,
                profiles=profiles,
                verbose=False,
            )
        finally:
            release_inference_slot()

        return {
            "accepted": result["is_accepted"],
            "action": "UNLOCK" if result["is_accepted"] else "DENY",
            "claimed_identity": claimed_identity,
            "similarity": round(result["similarity"], 4),
            "threshold_used": SERVER_THRESHOLD,
            "liveness_passed": True,
        }
    except HTTPException:
        raise
    except (ValueError, sf.LibsndfileError) as err:
        raise HTTPException(status_code=400, detail=f"Invalid or unreadable audio content: {err}")
    except RuntimeError as re:
        err_msg = str(re).lower()
        if "ffmpeg" in err_msg or "conversion failed" in err_msg:
            raise HTTPException(status_code=400, detail="Invalid audio stream or unreadable format.")
        raise HTTPException(status_code=500, detail="Biometric verification inference failed.")
    except Exception:
        raise HTTPException(status_code=500, detail="Biometric verification inference failed.")
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@router.websocket("/ws/identify")
async def ws_identify(websocket: WebSocket):
    """
    WebSocket endpoint for real-time speaker identification.
    Restricted to ADMIN. Requires initial authentication handshake before accepting audio.
    Enforces upload limits, session frame ceilings, and server-side calibrated threshold.
    """
    await websocket.accept()
    admin_user = await authenticate_ws_admin(websocket)
    get_sys = _get_system()
    profiles, classifier = get_sys()

    frame_count = 0
    max_frames = 100
    session_start_time = time.time()
    max_session_seconds = 300.0

    try:
        while True:
            audio_bytes = await websocket.receive_bytes()
            if time.time() - session_start_time > max_session_seconds:
                await websocket.send_json({"error": "Session duration limit exceeded (max 300s)."})
                await websocket.close(code=1008)
                break

            frame_count += 1
            if frame_count > max_frames:
                await websocket.send_json({"error": "Session frame limit exceeded (max 100 frames)."})
                await websocket.close(code=1008)
                break

            if not audio_bytes:
                await websocket.send_json({"error": "Empty audio payload"})
                continue
            if len(audio_bytes) > MAX_AUDIO_SIZE_BYTES:
                await websocket.send_json({"error": "Audio payload exceeds size limit"})
                continue

            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = Path(tmp.name)

            try:
                await acquire_inference_slot()
                try:
                    predict_fn = _get_predict_speaker()
                    result = predict_fn(
                        audio_path=str(tmp_path),
                        threshold=SERVER_THRESHOLD,
                        classifier=classifier,
                        profiles=profiles,
                        verbose=False,
                    )
                finally:
                    release_inference_slot()

                await websocket.send_json({
                    "speaker": result["predicted_speaker"],
                    "score": round(result["similarity"], 4),
                    "is_unknown": result["is_unknown"],
                    "threshold_used": SERVER_THRESHOLD,
                })
            except Exception:
                await websocket.send_json({"error": "Biometric inference failed"})
            finally:
                if tmp_path.exists():
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

    except WebSocketDisconnect:
        pass
