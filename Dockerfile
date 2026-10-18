# VoiceLock Enterprise — Secure Production Backend Container Image
# Multi-stage or clean single-stage Python runtime for FastAPI + SpeechBrain + Vosk

FROM python:3.11-slim

# Set non-interactive debconf and runtime environment flags
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    HOST=0.0.0.0

# Install OS-level dependencies required for audio transcoding and health probes:
# - ffmpeg: audio normalization (16kHz mono PCM16) in audio_utils.py
# - libsndfile1: C library backend for soundfile Python package
# - curl: container health check probe
# - ca-certificates: HTTPS validation for model downloads and Firebase
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged application user and group
RUN groupadd -g 10001 voicelock && \
    useradd -u 10001 -g voicelock -s /bin/bash -m voicelock

# Set application working directory
WORKDIR /app

# Copy dependency specifications first to leverage Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code (filtered strictly by .dockerignore)
COPY . .

# Pre-download and cache SpeechBrain ECAPA-TDNN and Vosk STT models
# into /app/.model_cache so the container is self-contained with zero runtime download needs
RUN python scripts/warmup_models.py

# Assign full ownership of application files and model cache to non-root user
RUN chown -R voicelock:voicelock /app

# Switch to unprivileged runtime user
USER voicelock

# Expose backend service port
EXPOSE 8000

# Container health check probing existing public discovery endpoint (GET /)
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Default runtime entrypoint
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
