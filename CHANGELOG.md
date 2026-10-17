# Changelog — VoiceLock Enterprise

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Semantic Versioning.

---

## [Unreleased]

### Added
- **Milestone 3B.2: IoT Device Authentication, ASGI Request Protection, CORS Hardening, Rate Limiting**
  - Implemented IoT Device Authentication module `app/core/device_auth.py`:
    - Replay-resistant HMAC-SHA256 signature scheme using device identifier, timestamp, cryptographically random nonce, HTTP method/path, and SHA-256 body hash.
    - Constant-time signature comparison (`hmac.compare_digest`) rejecting tampering.
    - In-memory nonce store (`InMemoryNonceStore`) with automatic TTL-based expiration and pruning preventing replay attacks.
    - Pre-shared secret key fallback (`X-Device-Key`) with documented limitations for low-capability embedded devices.
    - Fail-closed device registry (`VOICELOCK_DEVICE_REGISTRY`) requiring explicit configuration in production.
    - Mandatory HTTPS enforcement in production; reject credentials in query parameters (HTTP 400).
    - Authenticated device identity (`AuthenticatedDevice`) strictly assigned `Role.DEVICE` with zero administrative permissions (`is_admin=False`).
    - Unified actor dependency (`get_current_actor`) seamlessly authenticating Web Users (Bearer token) or IoT Devices (`X-Device-*` headers).
  - Implemented Reviewer Corrections:
    - **Correction A (Admin Custom Claim Guard):** Firebase custom claims are never trusted blindly; `TRUST_TOKEN_ADMIN_CLAIMS` defaults to `False` in production, requiring server-side bootstrap (`ADMIN_EMAILS`, `ADMIN_UIDS`).
    - **Correction B (Identity Binding Enforcement):** Ordinary `Role.USER` web accounts are strictly restricted to verifying their own enrolled voice identity (`resolve_user_voice_identity`), preventing arbitrary identity spoofing. Trusted `Role.DEVICE` and `Role.ADMIN` are authorized to verify enrolled speakers at the access portal.
  - Implemented ASGI Request-Body Size Limiter Middleware `app/core/middleware.py`:
    - `RequestSizeLimiterMiddleware`: True streaming ASGI inspection intercepting incoming body chunks before Starlette multipart disk parsing.
    - Fast-path header validation and streaming accumulator rejecting payloads exceeding `MAX_AUDIO_SIZE_BYTES` (5 MB) with HTTP 413.
    - Handles missing `Content-Length`, chunked transfer encoding, and misleading/tampered `Content-Length` headers.
    - Never leaks biometric data or authorization tokens in error logs.
  - Implemented Explicit CORS Hardening in `app/core/config.py` & `app/main.py`:
    - `ALLOWED_CORS_ORIGINS` setting with fail-closed validation rejecting wildcard `*` when credentials are enabled.
    - Defaults to explicit localhost origins for local development; requires explicit origin configuration in production.
  - Implemented Sliding-Window Rate Limiting & Resource Protection `app/core/rate_limit.py`:
    - Thread-safe in-memory sliding window rate limiter (`InMemoryRateLimiter`) with automatic timestamp pruning.
    - Applied to `POST /challenge` (30 req/min), `POST /verify` (10 req/min), `POST /identify` (10 req/min).
    - Rejection with HTTP 429 and RFC 7231 `Retry-After` header.
    - Concurrency semaphore (`MAX_CONCURRENT_INFERENCES = 4`) bounding simultaneous SpeechBrain ECAPA-TDNN feature extractions to prevent thread pool exhaustion and CPU starvation.
    - WebSocket streaming frame ceiling (maximum 100 frames/session) closing abusive streaming connections with WS close code 1008 (Policy Violation).
  - Expanded automated test suite with 25 comprehensive tests in `tests/test_device_auth.py`, bringing total suite to 89 passing tests.

- Implemented server-side Firebase ID-token verification module `app/core/auth.py` using `firebase-admin` (v7.7.0):
  - Single-instance lifecycle initialization (`get_firebase_app`) with ADC and service account support.
  - Strict production fail-closed security preventing insecure fallbacks and mock verifier execution in production.
  - Token extraction, schema validation, signature verification, and expiration enforcement.
  - Mandatory token revocation checking (`check_revoked=True`) on sensitive administrative endpoints.
  - Trusted server-side role resolution from verified token claims or server-side environment lists (`ADMIN_EMAILS`, `ADMIN_UIDS`), rejecting client role tampering.
  - Handshake-based WebSocket administrative authentication helper (`authenticate_ws_admin`).
- Enforced Role-Based Access Control (RBAC) across FastAPI endpoints:
  - `GET /`: Hardened public health discovery returning only non-sensitive metadata (redacted threshold and speaker counts).
  - `GET /speakers`: Restricted strictly to `Role.ADMIN` with token revocation check.
  - `POST /identify`: Restricted strictly to `Role.ADMIN` with token revocation check.
  - `POST /challenge`: Restricted to authenticated web users (`Role.USER` or `Role.ADMIN`).
  - `POST /verify`: Restricted to authenticated web users (`Role.USER` or `Role.ADMIN`), preserving challenge binding, single-use invalidation, liveness check, and server-controlled threshold.
  - `WS /ws/identify`: Restricted to `Role.ADMIN` via initial JSON auth handshake frame before audio streaming.
- Added comprehensive 21-test security test suite in `tests/test_auth.py` covering missing/malformed headers, invalid/expired/revoked tokens, role tampering, bootstrap role assignment, production environment guards, and WebSocket authentication.
- Expanded total automated test suite to 63 passing tests across API, security, and policy domains.
- Created declarative authentication policy module `app/core/auth_policy.py` defining:
  - Strict decoupling between `IdentityType.WEB_USER`, `IdentityType.SPEAKER_VOICE`, and `IdentityType.IOT_DEVICE`.
  - Role-Based Access Control (`Role.ADMIN`, `Role.USER`, `Role.DEVICE`, `Role.ANONYMOUS`).
  - Declarative endpoint permission matrix (`ENDPOINT_POLICIES`) and query helpers.
- Added automated unit test suite `tests/test_auth_policy.py` (7 tests), expanding total test suite to 42 passing tests.
- Added comprehensive authentication architecture and device verification flows in `ARCHITECTURE.md`.
- Added ADR 006 (Identity Separation & Dual-Credential Auth Architecture) in `DECISIONS.md`.
- Added ranked security vulnerability audit table in `SECURITY.md` (11 findings from Critical to Low).

- Modularized FastAPI backend into standard enterprise `app/` package layout:
  - `app/core/config.py`: Centralized configuration (`SERVER_THRESHOLD`, `MAX_AUDIO_SIZE_BYTES`, `ALLOWED_EXTENSIONS`) with defensive bounded loaders.
  - `app/core/errors.py`: Sanitized HTTP exception factories.
  - `app/schemas/`: Typed Pydantic data models for challenge requests/responses and verification contracts.
  - `app/services/`: Service layer separating model singleton caching (`speaker_service`), challenge management (`challenge_service`), and chunked audio upload spooling (`verification_service`).
  - `app/api/`: Sub-routers for `/` (health), `/speakers`, `/challenge`, and biometric routes (`/identify`, `/verify`, `/ws/identify`).
  - `app/main.py`: Application factory with modern FastAPI `lifespan` handler for single-pass model pre-warming.
- Refactored `cloud_api.py` as a 100% backward-compatible root entry point re-exporting all public symbols and functions.
- Implemented dynamic accessor lookup pattern in route handlers for test patch compatibility without circular dependencies.
- Added targeted test `test_verify_invalid_challenge_rejects_before_saving_upload`, expanding automated test suite to 35 tests.
- Implemented stateful liveness challenge engine (`liveness.py`) with `BaseChallengeStore` abstract interface and thread-safe `InMemoryChallengeStore`.
- Added cryptographically secure challenge generation using `secrets.randbelow(10)` (CSPRNG) and `secrets.token_hex(16)`.
- Added `POST /challenge` endpoint supporting both JSON and Form requests, binding challenges to session IDs and claimed speaker identities with 60-second TTL.
- Enforced challenge consumption in `POST /verify` with Single-Attempt Invalidation ('burn-on-use'), rejecting replay and concurrent duplicate submissions.
- Bound speaker verification to successful spoken digit liveness check; failed or unparseable audio denies access immediately without running ML inference.
- Expanded automated test suite with race-condition testing across 10 concurrent threads, deterministic expiry via clock injection, session binding, and fail-closed error handling.
- Added upfront `Content-Length` header verification in `save_upload()` to reject oversized payloads prior to reading request bodies.
- Added defensive configuration loaders `load_server_threshold()` and `load_max_audio_size()` with bounds checking and safe fallbacks.
- Added `pytest` and `httpx` to `requirements.txt`.
- Created `.env.example` with sanitized environment configuration template.
- Added comprehensive handoff documentation suite (`AGENTS.md`, `PROJECT_STATUS.md`, `ARCHITECTURE.md`, `DEVELOPMENT.md`, `DECISIONS.md`, `SECURITY.md`, `CHANGELOG.md`).

### Fixed
- Reordered verification pipeline in `POST /verify` to atomically validate and consume challenges *before* reading or spooling upload payloads, preventing resource exhaustion from invalid or expired requests.
- Replaced deprecated `@app.on_event("startup")` with modern FastAPI `lifespan` context manager, eliminating deprecation warnings.
- Fixed unhandled audio decoding errors (`soundfile.LibsndfileError`, FFmpeg conversion failures) by mapping them to HTTP 400 Bad Request instead of internal server errors.
- Fixed process termination in `predict.py` by replacing `sys.exit(1)` with `FileNotFoundError` and `ValueError`.
- Fixed `AttributeError: 'list' object has no attribute 'values'` in `tune_threshold.py`.
- Updated `.gitignore` to prevent tracking of `firebase-credentials.json`, `.env`, and private key files.

### Security
- Enforced early challenge invalidation and session check before disk I/O in `POST /verify`.
- Documented security boundary of caller-supplied `session_id` tokens as ephemeral correlation tokens rather than verified principal authentication.
- Documented in-memory challenge store boundaries and single-process deployment limits.
- Documented threat model boundary regarding spoken digit challenges and low-latency synthetic voice deepfakes.
- Replaced pseudo-random challenge generation (`random.randint`) with CSPRNG (`secrets.randbelow(10)`).
- Implemented single-attempt challenge invalidation ('burn-on-use') to defeat token replay and brute-force testing.
- Prevented concurrent submission race conditions via reentrant thread synchronization on challenge consumption.
- Bound challenge tokens to specific verification sessions and claimed speaker identities.
- Enforced server-side calibrated threshold (`SERVER_THRESHOLD = 0.25`) in API, ignoring and rejecting client threshold tampering.
- Implemented `MAX_AUDIO_SIZE_BYTES` (10MB) upload ceiling with HTTP 413 rejection and early `Content-Length` rejection.
- Enforced audio extension whitelisting (`.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`, `.aac`).
- Added guaranteed temporary file cleanup via `try/finally` across success, client disconnect, and error paths.
- Sanitized API error details to prevent leaking internal filesystem paths, transcripts, or stack traces.
- Isolated `firebase-credentials.json` on local filesystem and added rules preventing Git inclusion.


