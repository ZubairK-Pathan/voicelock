"""
app/services/verification_service.py — Audio upload handling and verification preprocessing.
"""

import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request, UploadFile

from app.core.config import ALLOWED_EXTENSIONS, MAX_AUDIO_SIZE_BYTES


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

    ext = Path(audio.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # 3. Stream upload in 64 KB chunks, tracking total bytes written
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    tmp_path = Path(tmp.name)
    total_bytes = 0

    try:
        while True:
            chunk = audio.file.read(65536)  # 64 KB chunks
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > MAX_AUDIO_SIZE_BYTES:
                tmp.close()
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"Audio file exceeds maximum allowed size ({MAX_AUDIO_SIZE_BYTES // (1024 * 1024)} MB).",
                )
            tmp.write(chunk)
        tmp.close()

        if total_bytes == 0:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")

        return tmp_path
    except HTTPException:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Failed to process audio upload: {str(exc)}")
