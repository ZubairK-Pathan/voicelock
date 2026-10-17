# Project Status — VoiceLock Enterprise

**Last Updated:** October 18, 2026  
**Current Milestone:** Milestone 3B.1 — Firebase Authentication, RBAC Enforcement, and Security Tests (Completed)  
**Current Git State:** Branch `feature/enterprise-foundation` (commit `e2f354f`, working tree updated with 3B.1 implementation)  
**Application Run Status:** Fully Operational (All 63 automated tests, Streamlit AppTest, ML inference, and calibration passing)

---

## 1. Executive Status
Milestone 3B.1 has implemented server-side Firebase ID-token bearer authentication, trusted server-side role resolution, and granular Role-Based Access Control (RBAC) enforcement across all FastAPI endpoints. The implementation utilizes the official `firebase-admin` SDK (v7.7.0) with single-instance lifecycle management, supports token revocation checks (`check_revoked=True`) on sensitive administrative operations, and strictly rejects client-supplied role tampering (e.g. `admin=true` query/form parameters). Endpoints `/speakers` and `/identify` are restricted to `Role.ADMIN`, `/challenge` and `/verify` require authenticated callers (`Role.USER` or `Role.ADMIN`), `GET /` is hardened to return non-sensitive public health metadata only, and `/ws/identify` enforces an upfront JSON authentication handshake frame before streaming audio. A dedicated 21-test security test suite (`tests/test_auth.py`) covers token expiration, revocation, malformed schemes, unauthorized role escalation, WebSocket handshake rejection, and production safeguards. The automated test suite has expanded to 63 passing tests with zero regressions on the Streamlit reference application or SpeechBrain ML pipeline.

---

## 2. Completed Milestones

### Milestone 0: Baseline Audit (Completed)
- Inspected full repository tree, commit history, and stash contents.
- Verified local runtime: Python 3.14.7, FFmpeg 8.1.2, Node.js v25.9.0.
- Audited ML models: ECAPA-TDNN (192-d vectors, CPU inference ~1.5s), 12 enrolled profiles.
- Verified baseline accuracy: 100% on held-out test sentences (Advait, Omar, Parth).
- Discovered and diagnosed `AttributeError` in `tune_threshold.py`.
- Identified security risks in `cloud_api.py`.

### Milestone 1: Safe Foundation & Security Baseline (Completed)
- Safely reverted unpushed local commit `310e8df` via `git reset --soft HEAD~1` without deleting or modifying local files.
- Verified `firebase-credentials.json` is physically preserved on disk, untracked, and ignored by Git.
- Created `feature/enterprise-foundation` branch rooted at `9587b59`.
- Updated `.gitignore` to prevent tracking of `firebase-credentials.json`, `.env*`, and private keys.
- Generated sanitized `.env.example` template with non-secret placeholders.
- Applied minimal bugfix to `tune_threshold.py` (resolving `all_embeddings.values()` crash).
- Audited statistical validity of EER threshold calculation (ADR 002 in `DECISIONS.md`).
- Established shared handoff documentation framework (7 files).

### Milestone 2A: Test Foundation & API Hardening (Completed)
- Installed `pytest` in `.venv` and updated `requirements.txt`.
- Built comprehensive automated test suite in `tests/test_api.py` covering health, listing, integration, missing audio, empty payloads, unsupported extensions, oversized payloads, threshold override resistance, empty profiles, and temp-file cleanup.
- Replaced `sys.exit()` in `predict.py` with `FileNotFoundError` and `ValueError`, while wrapping CLI `main()` with clean error handling.
- Hardened `cloud_api.py`:
  - Enforced server-controlled threshold `SERVER_THRESHOLD = 0.25` (ignoring/disallowing client threshold tampering).
  - Enforced `MAX_AUDIO_SIZE_BYTES = 10MB` with HTTP 413 rejection.
  - Added extension whitelist validation (`.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`, `.aac`).
  - Added robust chunked temp file writing and guaranteed `try/finally` cleanup on success, client disconnect, and error.
  - Sanitized error responses to prevent leaking internal filesystem paths or stack traces.
- Verified zero regressions on `evaluate.py`, `tune_threshold.py`, `predict.py`, and `app.py` (Streamlit AppTest).

### Milestone 2A.1: Security Review & Verification (Completed)
- **Review A (Upload Security):** Upfront `Content-Length` header inspection and 64KB chunked spooling. Unreadable audio mapped to HTTP 400.
- **Review B (Threshold Configuration):** Defensive `load_server_threshold()` and `load_max_audio_size()` bounded parsers. Tamper resistance verified.
- **Review C (API Test Quality):** Expanded tests from 13 to 20, verifying real security boundaries and temp-file lifecycle.
- **Review D (Error Handling & Regression):** Typed exceptions in `predict.py` verified; zero ML or UI regressions.

### Milestone 2B: Stateful Liveness Hardening (Completed)
- **Architecture & Interface:**
  - Defined `BaseChallengeStore` ABC with `create_challenge`, `get_challenge`, `validate_and_consume`, and `cleanup_expired`.
  - Implemented `InMemoryChallengeStore` using `threading.Lock` and injectable `time_func` clock abstraction for deterministic testing.
- **Lifecycle & Security Semantics:**
  - CSPRNG digit sequence generation (`secrets.randbelow(10)`) and 128-bit random challenge IDs (`secrets.token_hex(16)`).
  - Strict 60-second Time-to-Live (TTL).
  - Single-Attempt Invalidation ('burn-on-use') — challenge transitions to `CONSUMED` immediately on verification initiation, defeating replay attacks and concurrent duplicate submissions.
  - Session and speaker binding: challenges are strictly bound to a `session_id` and optional `claimed_identity`.
  - Fail-closed execution: liveness failures (wrong digits, silence, transcription failure) deny access and skip SpeechBrain ML inference.
- **API Endpoints:**
  - `POST /challenge`: Generates challenge with metadata; supports both JSON and Form payloads.
  - `POST /verify`: Requires `challenge_id` and `session_id`, enforces liveness passing before executing biometric verification.
- **Automated Tests:**
  - Expanded test suite from 20 to 34 automated tests, including race-condition testing across 10 concurrent threads, clock-injected expiry, and tamper resistance.
- **Streamlit Compatibility:**
  - Preserved backward-compatible function signatures in `liveness.py`, ensuring `app.py` runs with zero modifications.

### Milestone 2C: Security Review & Incremental API Modularization (Completed)
- **Early Challenge Invalidation Before Upload Processing:**
  - Reordered verification pipeline in `POST /verify`: atomically validates and consumes the challenge *before* calling `save_upload()`, preventing disk writes and buffering exhaustion from unauthorized, expired, or mismatched tokens.
  - Added automated test `test_verify_invalid_challenge_rejects_before_saving_upload`.
- **Modular Package Architecture (`app/`):**
  - `app/core/`: Centralized configuration (`config.py`) and typed error helpers (`errors.py`).
  - `app/schemas/`: Pydantic validation models for challenges (`challenge.py`) and verification/speakers/health (`verification.py`).
  - `app/services/`: Service layer isolating model caching (`speaker_service.py`), challenge operations (`challenge_service.py`), and chunked audio streaming (`verification_service.py`).
  - `app/api/`: Sub-routers for `routes_health.py`, `routes_speakers.py`, `routes_challenges.py`, and `routes_verification.py`.
  - `app/main.py`: Application factory (`create_app`) with modern FastAPI `lifespan` handler replacing deprecated `@app.on_event("startup")`.
- **Backward-Compatible Entry Point (`cloud_api.py`):**
  - Preserved `cloud_api.py` as a transparent root entry point re-exporting all symbols for CLI commands (`uvicorn cloud_api:app --host 0.0.0.0 --port 8000`) and integrations.
  - Implemented dynamic accessor lookup pattern in route controllers to seamlessly support `unittest.mock.patch("cloud_api.*")` without circular imports.
- **Verification & Zero Regressions:**
  - All 35 tests in `tests/test_api.py` pass cleanly in 1.2s.
  - Streamlit `app.py` AppTest passes with zero crashes.
  - ML inference, evaluation (27/27 correct, 100% accuracy), and threshold calibration execute successfully.

### Milestone 3A: Authentication Design & Security Review (Completed)
- **Comprehensive Threat Audit:** Identified 11 security findings ranked from Critical to Low:
  - Critical: Unauthenticated endpoints, user enumeration via `/speakers` & `/challenge`, and compute engine DoS via unconstrained ML inference.
  - High: Starlette multipart memory/disk buffering prior to route handler entry, unconstrained WebSocket frame ingestion, and in-memory challenge store memory limits.
  - Medium: Permissive CORS wildcard origins with credentials, public metric exposure in `/`, small EER sample size (27 recordings/3 speakers), and voice deepfake boundaries.
  - Low: Non-standard dynamic lookup adapter in routes.
- **Identity Decoupling:** Formally separated `IdentityType.WEB_USER` (Firebase JWT), `IdentityType.IOT_DEVICE` (Pre-Shared Key), and `IdentityType.SPEAKER_VOICE` (Passive 192-d biometric).
- **Declarative Access Policy Module:** Created `app/core/auth_policy.py` defining `Role`, `Permission`, and `ENDPOINT_POLICIES` matrix.
- **Automated Policy Tests:** Added `tests/test_auth_policy.py` (7 tests), expanding the test suite to 42 passing tests.
- **Documentation Updates:** Comprehensive updates to `ARCHITECTURE.md`, `SECURITY.md`, `DECISIONS.md` (ADR 006), and `DEVELOPMENT.md`.

### Milestone 3B.1: Firebase Authentication, RBAC Enforcement, and Security Tests (Completed)
- **Server-Side Firebase ID-Token Verification (`app/core/auth.py`):**
  - Utilizes official `firebase-admin` (v7.7.0) with single-instance initialization (`get_firebase_app`).
  - Supports credential resolution via `FIREBASE_CREDENTIALS_PATH`, local development fallback (outside production), and Google Application Default Credentials (ADC) in production.
  - Strict production fail-closed security: missing production credentials raise `RuntimeError`; test token verifier injection is prohibited when `VOICELOCK_ENV=production`.
  - Rejection with standard HTTP 401 (`WWW-Authenticate: Bearer ...`) for missing, malformed, invalid, and expired tokens.
  - Mandatory token revocation checking (`check_revoked=True`) on sensitive administrative operations.
- **Trusted Server-Side Role Assignment:**
  - Roles derived strictly from verified token custom claims (`admin: true`, `role: "admin"`, or `roles: [...]`) or server-side bootstrap environment lists (`ADMIN_EMAILS`, `ADMIN_UIDS`).
  - Client-supplied claims, parameters (e.g. `?admin=true`), or request fields are never trusted.
- **Endpoint Protection & Policy Alignment:**
  - `GET /`: Hardened public health discovery (redacted `threshold` and `enrolled_speakers`).
  - `GET /speakers`: Restricted strictly to `Role.ADMIN` with `check_revoked=True`.
  - `POST /identify`: Restricted strictly to `Role.ADMIN` with `check_revoked=True`.
  - `POST /challenge`: Restricted to authenticated web users (`Role.USER` or `Role.ADMIN`).
  - `POST /verify`: Restricted to authenticated web users (`Role.USER` or `Role.ADMIN`). Decoupled from `claimed_identity`. Preserves stateful challenge binding, single-use invalidation, liveness check, and server-controlled threshold.
  - `WS /ws/identify`: Restricted to `Role.ADMIN`. Enforces upfront JSON authentication handshake frame (`{"type": "auth", "token": "..."}`) within 5.0 seconds before streaming audio bytes. Closes unauthenticated or non-admin connections with code 1008.
- **Comprehensive Security Test Suite (`tests/test_auth.py`):**
  - Added 21 dedicated security tests covering missing bearer headers, malformed schemes, invalid signatures, expired tokens, revoked administrative tokens, unauthorized role escalation attempts, server-side bootstrap role assignment, production environment guards, WebSocket authentication handshake, challenge binding, and Streamlit independence.
- **Zero Regressions:**
  - Full test suite: 63 automated tests pass cleanly in 1.89s (35 API + 21 Auth Security + 7 Auth Policy).
  - Evaluation: 27/27 correct, 100% accuracy.
  - Calibration: EER 0.00% on test split.
  - Single inference: Zubair recognized with similarity 0.8668.
  - Streamlit `app.py` AppTest runs with zero crashes across all 4 tabs.

---

## 3. Verified Test Results
| Test Target | Command Executed | Exit Code | Result Summary |
| :--- | :--- | :--- | :--- |
| **Full Automated Test Suite** | `.venv/bin/pytest -v` | 0 | **63/63 tests PASSED in 1.89s** (35 API + 21 Auth Security + 7 Auth Policy) |
| **Auth Security Test Suite** | `.venv/bin/pytest tests/test_auth.py -v` | 0 | **21/21 tests PASSED** (token verification, RBAC, revocation, WS auth) |
| **Auth Policy Unit Tests** | `.venv/bin/pytest tests/test_auth_policy.py -v` | 0 | **7/7 tests PASSED** (identity separation, RBAC, endpoints) |
| **Model Inference** | `.venv/bin/python predict.py "processed_dataset/Zubair/Zubair_Enrollment_R01.wav"` | 0 | Identifies `Zubair` (Score: 0.8668, Margin: +0.6073) |
| **Evaluation Suite** | `.venv/bin/python evaluate.py` | 0 | 27/27 test samples correct (100% accuracy, Macro F1: 1.0) |
| **Threshold Calibration** | `.venv/bin/python tune_threshold.py` | 0 | Generates ROC/DET curves; Genuine Mean: 0.8136, Impostor: 0.2520 |
| **Streamlit Smoke Test** | `streamlit.testing.v1.AppTest.from_file('app.py')` | 0 | AppTest initializes, runs with zero exceptions across 4 tabs |

---

## 4. Known Issues & Remaining Security Risks
1. **Multipart Buffering in Starlette (`SEC-004`):**
   - *Risk:* Starlette buffers multipart payloads before route handlers execute. An attacker omitting `Content-Length` could force disk writes.
   - *Plan:* Add ASGI raw stream size limiter middleware in Milestone 3B.2 prior to multipart parsing.
2. **IoT Hardware Authentication Deferred (`SEC-001` partial):**
   - *Status:* Web user authentication is fully implemented; physical IoT terminal authentication (`X-Device-Key` / HMAC) is scheduled for Milestone 3B.2.
3. **In-Memory Challenge Store Single-Process Boundary (`SEC-006`):**
   - *Risk:* `InMemoryChallengeStore` is local to a single Python process. Running Uvicorn with `--workers > 1` causes state divergence.
   - *Plan:* Replace with Redis or PostgreSQL challenge store conforming to `BaseChallengeStore` in Milestone 3C.
4. **Small Evaluation Dataset & Threshold Discordance (`SEC-009`):**
   - *Risk:* 0.00% EER is computed on only 3 speakers (27 test samples). Max impostor score of 0.6802 exceeds baseline threshold of 0.25.
   - *Plan:* Retain 0.25 for prototype compatibility; conduct comprehensive multi-session biometric evaluation before production.
5. **Voice Cloning Limitations (`SEC-010`):**
   - *Risk:* Spoken digit challenge-response mitigates static replay attacks, but does not defeat low-latency real-time generative voice cloning.

---

## 5. Next Recommended Step
Proceed to **Milestone 3B.2: IoT Device Authentication & ASGI Upload Limiter**:
1. Implement IoT device authentication dependency (`get_current_device`) validating pre-shared keys (`X-Device-ID`, `X-Device-Key`).
2. Implement ASGI raw-stream body size limiter middleware to protect Starlette from unconstrained disk buffering.
3. Tighten CORS middleware in `app/main.py` with environment-controlled origins.
4. Add rate limiting middleware (`slowapi`) on `/verify` and `/challenge`.




