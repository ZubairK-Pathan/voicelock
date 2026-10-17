# Changelog — VoiceLock Enterprise

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Semantic Versioning.

---

## [Unreleased]

### Added
- Implemented stateful liveness challenge engine (`liveness.py`) with `BaseChallengeStore` abstract interface and thread-safe `InMemoryChallengeStore`.
- Added cryptographically secure challenge generation using `secrets.randbelow(10)` (CSPRNG) and `secrets.token_hex(16)`.
- Added `POST /challenge` endpoint in `cloud_api.py` supporting both JSON and Form requests, binding challenges to session IDs and claimed speaker identities with 60-second TTL.
- Enforced challenge consumption in `POST /verify` with Single-Attempt Invalidation ('burn-on-use'), rejecting replay and concurrent duplicate submissions.
- Bound speaker verification to successful spoken digit liveness check; failed or unparseable audio denies access immediately without running ML inference.
- Expanded automated test suite from 20 to 34 tests in `tests/test_api.py`, including race-condition testing across 10 concurrent threads, deterministic expiry via clock injection, session binding, and fail-closed error handling.
- Added automated test suite in `tests/test_api.py` with comprehensive unit, integration, and security edge case tests.
- Added upfront `Content-Length` header verification in `save_upload()` to reject oversized payloads prior to reading request bodies.
- Added defensive configuration loaders `load_server_threshold()` and `load_max_audio_size()` with bounds checking and safe fallbacks.
- Added `pytest` and `httpx` to `requirements.txt`.
- Created `.env.example` with sanitized environment configuration template.
- Added comprehensive handoff documentation suite (`AGENTS.md`, `PROJECT_STATUS.md`, `ARCHITECTURE.md`, `DEVELOPMENT.md`, `DECISIONS.md`, `SECURITY.md`, `CHANGELOG.md`).

### Fixed
- Fixed unhandled audio decoding errors (`soundfile.LibsndfileError`, FFmpeg conversion failures) by mapping them to HTTP 400 Bad Request instead of internal server errors.
- Fixed process termination in `predict.py` by replacing `sys.exit(1)` with `FileNotFoundError` and `ValueError`.
- Fixed `AttributeError: 'list' object has no attribute 'values'` in `tune_threshold.py`.
- Updated `.gitignore` to prevent tracking of `firebase-credentials.json`, `.env`, and private key files.

### Security
- Replaced pseudo-random challenge generation (`random.randint`) with CSPRNG (`secrets.randbelow(10)`).
- Implemented single-attempt challenge invalidation ('burn-on-use') to defeat token replay and brute-force testing.
- Prevented concurrent submission race conditions via reentrant thread synchronization on challenge consumption.
- Bound challenge tokens to specific verification sessions and claimed speaker identities.
- Enforced server-side calibrated threshold (`SERVER_THRESHOLD = 0.25`) in `cloud_api.py`, ignoring and rejecting client threshold tampering.
- Implemented `MAX_AUDIO_SIZE_BYTES` (10MB) upload ceiling with HTTP 413 rejection and early `Content-Length` rejection.
- Enforced audio extension whitelisting (`.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`, `.aac`).
- Added guaranteed temporary file cleanup via `try/finally` across success, client disconnect, and error paths.
- Sanitized API error details to prevent leaking internal filesystem paths, transcripts, or stack traces.
- Isolated `firebase-credentials.json` on local filesystem and added rules preventing Git inclusion.


