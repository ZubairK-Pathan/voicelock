#!/usr/bin/env python3
"""
cloud_api.py — FastAPI Cloud Inference Server for IoT Smart Lock

Deploy this file to any free cloud platform (see README for instructions).
An ESP32 or Raspberry Pi sends a POST request with audio bytes and gets
back a JSON decision — no ML runs on the device itself.

Supported protocols: HTTP REST (primary), WebSocket (real-time streaming)

Free deployment options (see CLOUD_SETUP.md):
  - Oracle Cloud Always Free (4 OCPUs, 24GB RAM) — RECOMMENDED
  - Hugging Face Spaces (FastAPI)                 — easiest, zero setup
  - Render.com free tier                          — simple, but sleeps after 15min

IoT → Cloud → IoT flow:
    ESP32 records audio (WAV bytes)
         │
         │  HTTP POST /verify  {audio: <bytes>, claimed_identity: "Omar"}
         ▼
    FastAPI (this file) running on cloud
         │  ECAPA-TDNN inference
         │
         ▼  JSON {"accepted": true, "score": 0.83, "speaker": "Omar"}
         │
    ESP32 reads response → opens relay (door unlock) or rejects

Usage (local testing):
    pip install fastapi uvicorn python-multipart
    uvicorn cloud_api:app --host 0.0.0.0 --port 8000
    curl -X POST http://localhost:8000/identify -F "audio=@test.wav"
"""

import io
import tempfile
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import soundfile as sf
import uvicorn

from predict import predict_speaker, verify_speaker, DEFAULT_THRESHOLD
from audio_utils import load_embedding_model, load_profiles
from liveness import (
    default_challenge_store,
    challenge_display,
    run_liveness_check,
    LivenessChallenge,
    BaseChallengeStore,
)

# ─── Configuration & Security Defaults ───────────────────────────────────────

def load_server_threshold() -> float:
    """
    Load and validate the server-side acceptance threshold.
    Guarantees a valid float bounded in [0.0, 1.0].
    Defaults safely to DEFAULT_THRESHOLD (0.25) if invalid or absent.
    """
    raw = os.getenv("DEFAULT_THRESHOLD")
    if raw is None or not raw.strip():
        return DEFAULT_THRESHOLD
    try:
        val = float(raw.strip())
        if 0.0 <= val <= 1.0:
            return val
    except (ValueError, TypeError):
        pass
    return DEFAULT_THRESHOLD


def load_max_audio_size() -> int:
    """
    Load and validate the maximum allowed upload size in bytes.
    Defaults to 10 MB (10,485,760 bytes) if invalid or absent.
    """
    default_size = 10 * 1024 * 1024  # 10 MB
    raw = os.getenv("MAX_AUDIO_SIZE_BYTES")
    if raw is None or not raw.strip():
        return default_size
    try:
        val = int(raw.strip())
        if val > 0:
            return val
    except (ValueError, TypeError):
        pass
    return default_size


SERVER_THRESHOLD = load_server_threshold()
MAX_AUDIO_SIZE_BYTES = load_max_audio_size()
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}

app = FastAPI(
    title="Speaker Recognition API",
    description="Cloud inference endpoint for IoT voice-based access control.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_profiles = None
_classifier = None


def get_system():
    """Lazy-load and cache the model + profiles (loaded once on first request)."""
    global _profiles, _classifier
    if _profiles is None or _classifier is None:
        _profiles = load_profiles()
        _classifier = load_embedding_model()
    return _profiles, _classifier


def save_upload(audio: UploadFile, request: Optional[Request] = None) -> Path:
    """
    Validate and save uploaded audio bytes to a temporary file.
    Enforces allowed extensions and strict file size limits (MAX_AUDIO_SIZE_BYTES).
    Checks Content-Length upfront if available, and streams in chunks.
    Cleans up the temporary file immediately on error.
    """
    # 1. Upfront Content-Length check if request is provided
    if request is not None:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_AUDIO_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Audio file exceeds maximum allowed size ({MAX_AUDIO_SIZE_BYTES // (1024 * 1024)} MB).",
                    )
            except ValueError:
                pass

    # 2. Filename and extension validation
    if not audio.filename:
        raise HTTPException(status_code=400, detail="Missing filename in audio upload.")

    suffix = Path(audio.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format '{suffix}'. Allowed formats: {sorted(list(ALLOWED_EXTENSIONS))}",
        )

    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    bytes_read = 0
    chunk_size = 64 * 1024  # 64 KB chunks

    try:
        while True:
            chunk = audio.file.read(chunk_size)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > MAX_AUDIO_SIZE_BYTES:
                tmp.close()
                if os.path.exists(tmp.name):
                    os.unlink(tmp.name)
                raise HTTPException(
                    status_code=413,
                    detail=f"Audio file exceeds maximum allowed size ({MAX_AUDIO_SIZE_BYTES // (1024 * 1024)} MB).",
                )
            tmp.write(chunk)
        tmp.close()

        if bytes_read == 0:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)
            raise HTTPException(status_code=400, detail="Audio payload is empty (0 bytes received).")

        return Path(tmp.name)

    except HTTPException:
        raise
    except Exception:
        tmp.close()
        if os.path.exists(tmp.name):
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail="Failed to process uploaded audio file.")


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/")
def root():
    """Health check — useful for IoT devices to verify the server is alive."""
    return {"status": "online", "service": "Speaker Recognition API"}


@app.get("/speakers")
def list_speakers():
    """Return the list of currently registered speakers."""
    profiles, _ = get_system()
    return {"registered_speakers": list(profiles.keys()), "count": len(profiles)}


@app.post("/identify")
async def identify(
    request: Request,
    audio: UploadFile = File(..., description="WAV/MP3/M4A audio file"),
    threshold: Optional[float] = Form(None, description="Deprecated client threshold; server enforces calibrated threshold"),
):
    """
    Identify who is speaking in the audio (1-to-N).
    Enforces server-side threshold and bounded upload limits.
    """
    profiles, classifier = get_system()
    if not profiles:
        raise HTTPException(status_code=503, detail="No speaker profiles are enrolled in the system.")

    tmp_path = save_upload(audio, request=request)
    try:
        result = predict_speaker(
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
        if tmp_path.exists():
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@app.post("/challenge")
async def create_challenge_endpoint(request: Request):
    """
    Generate an unpredictable, cryptographically secure 3-digit liveness challenge.
    Binds the challenge to a verification session and optionally to a claimed identity.
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

    profiles, _ = get_system()
    if claimed_identity is not None:
        clean_claimed = str(claimed_identity).strip()
        if profiles and clean_claimed not in profiles:
            raise HTTPException(
                status_code=404,
                detail=f"Speaker '{clean_claimed}' is not registered."
            )
        claimed_identity = clean_claimed

    challenge = default_challenge_store.create_challenge(
        session_id=str(session_id).strip() if session_id else None,
        claimed_identity=claimed_identity,
        ttl_seconds=60,
        length=3,
    )

    return {
        "challenge_id": challenge.challenge_id,
        "session_id": challenge.session_id,
        "claimed_identity": challenge.claimed_identity,
        "digits": challenge.digits,
        "display": challenge_display(challenge.digits),
        "expires_at": challenge.expires_at,
        "expires_in_seconds": 60,
    }


@app.post("/verify")
async def verify(
    request: Request,
    audio: UploadFile = File(..., description="WAV/MP3/M4A audio file containing spoken challenge digits"),
    claimed_identity: str = Form(..., description="Name of the speaker being claimed"),
    challenge_id: Optional[str] = Form(None, description="Active liveness challenge ID"),
    session_id: Optional[str] = Form(None, description="Active verification session ID"),
    threshold: Optional[float] = Form(None, description="Deprecated client threshold; server enforces calibrated threshold"),
):
    """
    Verify whether the audio matches the claimed speaker identity (1-to-1)
    AND satisfies the bound liveness challenge (anti-spoofing / anti-replay).
    
    Security workflow:
    1. Validates registration of claimed identity.
    2. Enforces presence of challenge_id and session_id.
    3. Atomically consumes the challenge (Single-Attempt Invalidation).
    4. Evaluates spoken digits against expected challenge via offline Vosk STT.
    5. If liveness fails, access is DENIED immediately without running ML inference.
    6. If liveness passes, runs ECAPA-TDNN speaker verification at SERVER_THRESHOLD.
    """
    profiles, classifier = get_system()
    if not profiles:
        raise HTTPException(status_code=503, detail="No speaker profiles are enrolled in the system.")

    claimed_identity = claimed_identity.strip()
    if not claimed_identity or claimed_identity not in profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Speaker '{claimed_identity}' is not registered."
        )

    # 1. Challenge & Session binding validation
    if not challenge_id or not str(challenge_id).strip() or not session_id or not str(session_id).strip():
        raise HTTPException(
            status_code=400,
            detail="Missing required challenge_id or session_id for verification."
        )

    clean_challenge_id = str(challenge_id).strip()
    clean_session_id = str(session_id).strip()

    # 2. Save upload and enforce upload limits
    tmp_path = save_upload(audio, request=request)

    try:
        # 3. Atomically consume challenge (burn on use)
        valid, reason, challenge = default_challenge_store.validate_and_consume(
            challenge_id=clean_challenge_id,
            session_id=clean_session_id,
            claimed_identity=claimed_identity,
        )
        if not valid or challenge is None:
            raise HTTPException(status_code=400, detail=reason)

        # 4. Spoken liveness verification (Vosk STT challenge evaluation)
        is_live, liveness_reason, _ = run_liveness_check(str(tmp_path), challenge.digits)
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

        # 5. Biometric speaker verification (SpeechBrain ECAPA-TDNN)
        result = verify_speaker(
            audio_path=str(tmp_path),
            claimed_identity=claimed_identity,
            threshold=SERVER_THRESHOLD,
            classifier=classifier,
            profiles=profiles,
            verbose=False,
        )
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
        if tmp_path.exists():
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ─── WebSocket (for real-time streaming) ─────────────────────────────────────

from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/identify")
async def ws_identify(websocket: WebSocket):
    """
    WebSocket endpoint for real-time speaker identification.
    Enforces upload limits and server-side calibrated threshold.
    """
    await websocket.accept()
    profiles, classifier = get_system()
    try:
        while True:
            audio_bytes = await websocket.receive_bytes()
            if not audio_bytes:
                await websocket.send_json({"error": "Empty audio payload"})
                continue
            if len(audio_bytes) > MAX_AUDIO_SIZE_BYTES:
                await websocket.send_json({"error": "Audio payload exceeds size limit"})
                continue

            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.write(audio_bytes)
            tmp.close()

            try:
                result = predict_speaker(
                    audio_path=tmp.name,
                    threshold=SERVER_THRESHOLD,
                    classifier=classifier,
                    profiles=profiles,
                    verbose=False,
                )
                await websocket.send_json({
                    "speaker": result["predicted_speaker"],
                    "score": round(result["similarity"], 4),
                    "is_unknown": result["is_unknown"],
                    "threshold_used": SERVER_THRESHOLD,
                })
            except Exception:
                await websocket.send_json({"error": "Biometric inference failed"})
            finally:
                if os.path.exists(tmp.name):
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass

    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    uvicorn.run("cloud_api:app", host="0.0.0.0", port=8000, reload=False)
