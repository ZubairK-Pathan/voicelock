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

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from predict import predict_speaker, verify_speaker, DEFAULT_THRESHOLD
from audio_utils import load_embedding_model, load_profiles

# ─── Configuration & Security Defaults ───────────────────────────────────────
SERVER_THRESHOLD = float(os.getenv("DEFAULT_THRESHOLD", str(DEFAULT_THRESHOLD)))
MAX_AUDIO_SIZE_BYTES = int(os.getenv("MAX_AUDIO_SIZE_BYTES", str(10 * 1024 * 1024)))  # 10 MB limit
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


def save_upload(audio: UploadFile) -> Path:
    """
    Validate and save uploaded audio bytes to a temporary file.
    Enforces allowed extensions and strict file size limits (MAX_AUDIO_SIZE_BYTES).
    Cleans up the temporary file on error.
    """
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

    tmp_path = save_upload(audio)
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
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception:
        raise HTTPException(status_code=500, detail="Biometric identification inference failed.")
    finally:
        if tmp_path.exists():
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@app.post("/verify")
async def verify(
    audio: UploadFile = File(..., description="WAV/MP3/M4A audio file"),
    claimed_identity: str = Form(..., description="Name of the speaker being claimed"),
    threshold: Optional[float] = Form(None, description="Deprecated client threshold; server enforces calibrated threshold"),
):
    """
    Verify whether the audio matches the claimed speaker identity (1-to-1).
    Enforces server-side threshold and bounded upload limits.
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

    tmp_path = save_upload(audio)
    try:
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
            "claimed_identity": claimed_identity,
            "similarity": round(result["similarity"], 4),
            "threshold_used": SERVER_THRESHOLD,
            "action": "UNLOCK" if result["is_accepted"] else "DENY",
        }
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
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
