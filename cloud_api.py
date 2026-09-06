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
    """Save uploaded audio bytes to a temp file and return its path."""
    suffix = Path(audio.filename or "audio.wav").suffix or ".wav"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(audio.file.read())
    tmp.close()
    return Path(tmp.name)


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
    threshold: float = Form(DEFAULT_THRESHOLD),
):
    """
    Identify who is speaking in the audio (1-to-N).

    Send a multipart form POST with an audio file.
    Returns the predicted speaker, similarity score, and all scores.

    Example (curl):
        curl -X POST http://YOUR_SERVER/identify \\
             -F "audio=@recording.wav" \\
             -F "threshold=0.30"

    Example (Python requests — for Raspberry Pi):
        import requests
        with open("recording.wav", "rb") as f:
            r = requests.post("http://YOUR_SERVER/identify",
                              files={"audio": f},
                              data={"threshold": 0.30})
        print(r.json())
    """
    profiles, classifier = get_system()
    tmp_path = save_upload(audio)
    try:
        result = predict_speaker(
            audio_path=str(tmp_path),
            threshold=threshold,
            classifier=classifier,
            profiles=profiles,
            verbose=False,
        )
        return {
            "predicted_speaker": result["predicted_speaker"],
            "similarity": round(result["similarity"], 4),
            "is_unknown": result["is_unknown"],
            "all_scores": {k: round(v, 4) for k, v in result["all_scores"].items()},
            "threshold_used": threshold,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)


@app.post("/verify")
async def verify(
    audio: UploadFile = File(..., description="WAV/MP3/M4A audio file"),
    claimed_identity: str = Form(..., description="Name of the speaker being claimed"),
    threshold: float = Form(DEFAULT_THRESHOLD),
):
    """
    Verify whether the audio matches the claimed speaker identity (1-to-1).

    This is the primary endpoint for an IoT smart lock:
    - ESP32 sends audio + "Omar" as claimed_identity
    - API returns {"accepted": true/false}
    - ESP32 opens or keeps the lock based on the response

    Example (MicroPython on ESP32):
        import urequests, machine
        with open("audio.wav", "rb") as f:
            audio_bytes = f.read()
        r = urequests.post(
            "http://YOUR_SERVER/verify",
            headers={"Content-Type": "multipart/form-data"},
            data={"claimed_identity": "Omar", "threshold": "0.30"},
            files={"audio": ("audio.wav", audio_bytes, "audio/wav")}
        )
        if r.json()["accepted"]:
            machine.Pin(RELAY_PIN, machine.Pin.OUT).value(1)  # unlock
    """
    profiles, classifier = get_system()
    if claimed_identity not in profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Speaker '{claimed_identity}' is not registered."
        )

    tmp_path = save_upload(audio)
    try:
        result = verify_speaker(
            audio_path=str(tmp_path),
            claimed_identity=claimed_identity,
            threshold=threshold,
            classifier=classifier,
            profiles=profiles,
            verbose=False,
        )
        return {
            "accepted": result["is_accepted"],
            "claimed_identity": claimed_identity,
            "similarity": round(result["similarity"], 4),
            "threshold_used": threshold,
            "action": "UNLOCK" if result["is_accepted"] else "DENY",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)


# ─── WebSocket (for real-time streaming) ─────────────────────────────────────

from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/identify")
async def ws_identify(websocket: WebSocket):
    """
    WebSocket endpoint for real-time speaker identification.

    The client sends raw audio bytes in chunks.
    The server responds with JSON identification result.

    Use this when you want near-real-time feedback (e.g., a smart speaker
    that continuously listens and shows who is currently talking).

    Protocol:
        Client sends: binary audio bytes (WAV format, complete file)
        Server sends: JSON string with identification result
    """
    await websocket.accept()
    profiles, classifier = get_system()
    try:
        while True:
            audio_bytes = await websocket.receive_bytes()

            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.write(audio_bytes)
            tmp.close()

            try:
                result = predict_speaker(
                    audio_path=tmp.name,
                    classifier=classifier,
                    profiles=profiles,
                    verbose=False,
                )
                await websocket.send_json({
                    "speaker": result["predicted_speaker"],
                    "score": round(result["similarity"], 4),
                    "is_unknown": result["is_unknown"],
                })
            except Exception as e:
                await websocket.send_json({"error": str(e)})
            finally:
                os.unlink(tmp.name)

    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    uvicorn.run("cloud_api:app", host="0.0.0.0", port=8000, reload=False)
