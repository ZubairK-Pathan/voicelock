# Project Status — VoiceLock Enterprise

**Last Updated:** October 18, 2026  
**Current Milestone:** Milestone 3C.2c.1 — Persistent User-to-Speaker Identity Mapping Schema & Migration (Completed)  
**Current Git State:** Branch `feature/enterprise-foundation` (commit `ea37294`, working tree updated with 3C.2c.1 implementation)  
**Application Run Status:** Fully Operational (All 121 automated tests, Streamlit AppTest, ML inference, and calibration passing)

---

## 1. Executive Status
Milestone 3C.2c.1 establishes the persistent database schema and migration infrastructure for mapping authenticated application users (Firebase UID) to enrolled biometric speaker identities (`speakers.speaker_id`). Implemented via `UserSpeakerMapping` in `app/db/base.py`, the design enforces a strict 1-to-1 cardinality via unique indexes on both `firebase_uid` and `speaker_id`, coupled with cascading foreign key referential integrity (`ForeignKey("speakers.speaker_id", ondelete="CASCADE")`). This guarantees identity non-repudiation: a physical voiceprint cannot be shared across multiple user accounts (eliminating audit ambiguity), and an ordinary user cannot verify against multiple voiceprints. The schema strictly excludes credentials, tokens, and biometric raw data. Alembic migration `0b98eaf9dc3e_create_user_speaker_mappings_table.py` was created and validated with end-to-end upgrade, foreign key verification, 1-to-1 uniqueness rejection, and single-revision rollback against disposable SQLite databases. The automated test suite has expanded to 121 tests passing in 2.77s with zero regressions. Authorization enforcement is deliberately preserved for Milestone 3C.2c.2.

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

### Milestone 3B.2: IoT Device Authentication, ASGI Upload Limiter, CORS, and Rate Limiting (Completed)
- **IoT Device Authentication Dependency (`app/core/device_auth.py`):**
  - Implemented `get_current_device` dependency supporting dual authentication schemes:
    - Scheme A (Recommended): Replay-resistant HMAC-SHA256 protocol with canonical signing `f"{method}\n{path}\n{timestamp}\n{nonce}\n{body_sha256}"`, 300s timestamp tolerance window, constant-time validation (`hmac.compare_digest`), and thread-safe sliding window `InMemoryNonceStore` anti-replay defense.
    - Scheme B: Pre-shared key fallback (`X-Device-Key`) over HTTPS with documented trade-offs regarding replay resistance.
  - Fail-closed security: missing/empty device registry fails with HTTP 500; plain HTTP device requests rejected in production with HTTP 403; device credentials in URL query parameters strictly rejected with HTTP 400.
  - Privilege separation: devices are strictly assigned `Role.DEVICE` and never `Role.ADMIN`. Restricted to `POST /challenge` and `POST /verify`.
- **Reviewer Corrections A & B Enforced:**
  - Correction A: Firebase token custom claims (`admin: true`) are guarded by `TRUST_TOKEN_ADMIN_CLAIMS` (defaults to `false` in production). Admin role is granted only via server-side bootstrap registries (`ADMIN_EMAILS`, `ADMIN_UIDS`) or authoritative administrative backend.
  - Correction B: Ordinary web users (`Role.USER`) are authorized ONLY to verify their own voice identity (`resolve_user_voice_identity`). Arbitrary claimed identities yield HTTP 403. Trusted devices (`Role.DEVICE`) and admins can verify enrolled speakers at the door portal.
- **ASGI Request-Body Streaming Limiter (`app/core/middleware.py`):**
  - Fast upfront verification of declared `Content-Length`.
  - Raw stream inspection via `limited_receive` wrapping ASGI `receive` callable. Counts cumulative byte chunks on-the-fly and terminates immediately with HTTP 413 (`PayloadTooLargeError`) without buffering entire payload or spooling to disk.
  - Route ceilings: 10 MB + 64 KB for upload routes (`/verify`, `/identify`), 1 MB for standard endpoints.
- **CORS Hardening (`app/core/config.py`):**
  - Explicit allowed origins via `load_allowed_cors_origins()`.
  - Rejects wildcard `*` with `ValueError` when credentials are enabled. Local development defaults to `localhost:3000/5173/8501`.
- **Rate Limiting & Resource Protection (`app/core/rate_limit.py`):**
  - Sliding-window in-memory limiter with automatic pruning of expired timestamps to bound memory.
  - Endpoints protected: `POST /challenge` (30/min), `POST /verify` (30/min), `POST /identify` (15/min), and `WS /ws/identify` (100 frames/session).
  - Inference concurrency semaphore (`asyncio.Semaphore(4)`) prevents CPU core starvation from parallel ECAPA-TDNN feature extractions.
- **Dedicated Test Suite (`tests/test_device_auth.py`):**
  - Added 25 tests covering HMAC signatures, pre-shared keys, nonce replays, stale timestamps, query parameter rejection, privilege separation, plain HTTP rejection, ASGI stream limits (with and without Content-Length, misleading Content-Length), multipart parsing, CORS allow/deny, rate limits (HTTP 429 + Retry-After), and WebSocket frame limits.
- **Zero Regressions:**
  - 89 automated tests pass cleanly in 2.25s (35 API + 22 Auth + 7 Policy + 25 Device Auth).
  - Evaluation: 27/27 correct, 100% accuracy.
  - Calibration: EER 0.00% on test split.
  - Single inference: Zubair recognized with similarity 0.8668.
  - Streamlit `app.py` AppTest runs with zero crashes across all 4 tabs.

### Milestone 3C.1: SQLAlchemy 2.0 & Alembic Database Foundation (Completed)
- **Centralized Database Configuration (`app/db/session.py`):**
  - Dynamic URL resolution via `get_database_url()` reading `DATABASE_URL` from environment.
  - Automatic URL dialect normalization (`postgres://` / `postgresql://` -> `postgresql+psycopg://`).
  - Credential masking utility (`mask_database_url`) preventing plaintext password leakage in logs.
  - Fail-closed production safety: raises `RuntimeError` if `DATABASE_URL` is missing in production environments (`VOICELOCK_ENV=production`).
  - Lazy initialization with `threading.RLock()`: avoids unsolicited database connections at module import time, preserving CLI scripts, ML inference, and Streamlit reference app.
  - Production connection pooling: `QueuePool` with bounded size (`DB_POOL_SIZE=5`), max overflow (`DB_MAX_OVERFLOW=10`), connection recycle (`DB_POOL_RECYCLE=1800`), timeout (`DB_POOL_TIMEOUT=30.0`), and keepalive `pool_pre_ping=True`.
  - In-memory SQLite support using `StaticPool` for local test isolation without external dependencies.
  - FastAPI dependency `get_db()` and context manager `get_db_context()` supporting clean session lifecycle and transaction commit/rollback.
- **Alembic Migration Infrastructure (`alembic.ini`, `alembic/`):**
  - Alembic environment (`alembic/env.py`) configured with dynamic database URL resolution from `get_database_url()` and `Base.metadata`.
  - Initial migration script (`e32dc984b290_create_schema_initializations_table.py`) creating foundational `schema_initializations` verification table.
  - Verified complete migration lifecycle: automated test performs end-to-end `upgrade("head")`, schema inspection, and `downgrade("base")` against a disposable database.
- **Declarative Schema Base (`app/db/base.py`):**
  - SQLAlchemy 2.0 `DeclarativeBase` established.
  - Minimal `SchemaInitialization` model recording database initialization timestamp and version.
- **Automated Database Test Suite (`tests/test_database.py`):**
  - Added 13 dedicated tests covering URL normalization, fail-closed production semantics, password masking, pool configuration, lazy initialization, transaction commit/rollback, FastAPI dependency, and full Alembic upgrade/downgrade lifecycle.
  - Full test suite expanded to 107 passing tests in 2.60s with zero regressions.

### Milestone 3C.2a: Speaker Registry Schema & Migration (Completed)
- **Declarative Speaker Model (`app/db/base.py`):**
  - Created `SpeakerRecord` entity mapping table `speakers`.
  - Defined fields: `id` (PK), `speaker_id` (unique indexed string, matching enrolled identities), `full_name` (optional string), `status` (default="active"), `embedding_dim` (default=192), `sample_count` (default=1), `created_at` / `updated_at` (timezone-aware UTC timestamps), and `metadata_json` (flexible JSON text).
  - Added `@property is_active` helper.
  - Re-exported `SpeakerRecord` in `app/db/__init__.py` and `app/core/database.py`.
- **Alembic Migration (`a4ae5dfd43b3_create_speakers_table.py`):**
  - Created revision chained to `e32dc984b290`.
  - Implemented `upgrade()` to generate `speakers` table with constraints and unique index on `speaker_id`.
  - Implemented `downgrade()` to cleanly drop index and table.
- **Automated Schema & Lifecycle Tests (`tests/test_database.py`):**
  - Added `test_speakers_schema_migration_and_constraints` validating migration upgrade, ORM insert and query, unique constraint enforcement on `speaker_id`, single-revision rollback, and re-upgrade.
  - Expanded test suite to 108 passing tests.
- **Workflow & Contribution Policy Alignment:**
  - Formally codified 15-rule incremental commit-and-push policy in `AGENTS.md` and `DEVELOPMENT.md`.

### Milestone 3C.2b: Speaker Registry Repository & Unit Tests (Completed)
- **Data Access Repository (`app/repositories/speaker_repository.py`):**
  - Implemented `SpeakerRepository` using SQLAlchemy 2.0 (`select`, `scalars`, `session.get`, `session.flush`).
  - Supported operations:
    - `create()`: Input validation (`speaker_id` non-empty, `status in {"active", "suspended", "revoked"}`, `embedding_dim > 0`, `sample_count >= 1`), constraint enforcement, and automatic handling of `IntegrityError` mapped to `DuplicateSpeakerError`.
    - `get_by_speaker_id()` and `get_by_id()`: Clean point lookups.
    - `get_or_raise()`: Predictable missing record handling raising typed `SpeakerNotFoundError`.
    - `list_speakers()`: Sorted alphabetical listing with optional `active_only` filtering and pagination (`limit`, `offset`).
    - `get_active_speaker_ids()`: Fast lookup of active speaker strings for biometric validation pipelines.
    - `update()`: Modifies permitted metadata, updates lifecycle status, advances `updated_at`, and validates inputs.
    - `delete()`: Deletes record and returns boolean success.
    - `count()`: Aggregates total or active speaker counts via SQL `func.count`.
  - Transaction safety: operations use `session.flush()` without calling `session.commit()`, ensuring transaction ownership remains strictly with the caller (FastAPI dependency or context manager).
  - Package re-exports: exported in `app/repositories/__init__.py` and `app/db/__init__.py`.
- **Dedicated Unit Test Suite (`tests/test_speaker_repository.py`):**
  - Added 12 comprehensive unit tests using isolated disposable SQLite databases:
    - Non-null session requirement.
    - Happy path creation and field verification.
    - Input validation on create (empty ID, invalid status, invalid dimensions).
    - Unique constraint rejection (`DuplicateSpeakerError`).
    - Query by string ID and integer primary key.
    - Predictable not-found behavior (`None` vs `SpeakerNotFoundError`).
    - Listing, alphabetical ordering, active-only filtering, and pagination.
    - Metadata and status updates with `updated_at` advancement.
    - Invalid status updates rejected.
    - Record deletion and post-deletion lookup.
    - Total and active count aggregations.
    - Explicit transaction boundary verification (caller rollback drops uncommitted repo changes).
  - Expanded total automated test suite from 108 to 120 passing tests.

### Milestone 3C.2c.1: Persistent User-to-Speaker Identity Mapping Schema & Migration (Completed)
- **Declarative Identity Mapping Model (`app/db/base.py`):**
  - Created `UserSpeakerMapping` entity mapping the `user_speaker_mappings` table.
  - Defined fields:
    - `id`: Autoincrement primary key (`Integer`).
    - `firebase_uid`: External application user identifier (`String(128)`, unique, indexed, non-null).
    - `speaker_id`: Enrolled voice identity (`String(64)`, unique, indexed, non-null) with foreign key `ForeignKey("speakers.speaker_id", ondelete="CASCADE")`.
    - `assigned_by`: Audit trail identifier of the provisioning admin/bootstrap (`String(128)`, nullable).
    - `created_at` / `updated_at`: Timezone-aware UTC timestamps (`DateTime(timezone=True)`).
    - `metadata_json`: Provisioning metadata (`Text`, nullable).
    - ORM relationship `speaker` mapped back to `SpeakerRecord`.
  - Re-exported `UserSpeakerMapping` in `app/db/__init__.py` and `app/core/database.py`.
- **Cardinality Decision & Rationale:**
  - **Decision:** Strict 1-to-1 cardinality enforced through independent `UNIQUE` constraints on both `firebase_uid` and `speaker_id`.
  - **Rationale:** Non-repudiation in enterprise biometric authentication mandates that a human voiceprint cannot be shared across multiple user accounts (preventing credential sharing, delegation, and audit trail ambiguity). Similarly, an ordinary user account cannot impersonate or verify on behalf of multiple enrolled speaker identities.
- **Data Protection & Secret Exclusion:**
  - Strictly excludes Firebase passwords, ID tokens, service account credentials, biometric audio recordings, and 192-d embedding vectors.
- **Alembic Migration (`0b98eaf9dc3e_create_user_speaker_mappings_table.py`):**
  - Created revision chained to `a4ae5dfd43b3` (`create_speakers_table`).
  - Implemented `upgrade()` and `downgrade()` managing table creation, foreign keys, unique indices, and cleanup.
- **Automated Schema & Constraint Tests (`tests/test_database.py`):**
  - Added `test_user_speaker_mappings_schema_migration_and_constraints`:
    - Verifies migration upgrade to head, foreign key inspection to `speakers.speaker_id`, and unique index existence.
    - Validates valid insertion and ORM relationship traversal.
    - Enforces 1-to-1 uniqueness: duplicate `firebase_uid` raises `IntegrityError`; duplicate `speaker_id` raises `IntegrityError`.
    - Validates single-revision rollback (`0b98eaf9dc3e -> a4ae5dfd43b3`) dropping `user_speaker_mappings` while retaining `speakers` and `schema_initializations`.
    - Verifies re-application of `upgrade head`.
  - Total automated tests expanded to 121 passing tests in 2.77s.

---

## 3. Verified Test Results
| Test Target | Command Executed | Exit Code | Result Summary |
| :--- | :--- | :--- | :--- |
| **Full Automated Test Suite** | `.venv/bin/pytest -v` | 0 | **121/121 tests PASSED in 2.77s** (35 API + 22 Auth + 7 Policy + 30 Device Auth + 15 Database + 12 Speaker Repository) |
| **Database Foundation Suite** | `.venv/bin/pytest tests/test_database.py -v` | 0 | **15/15 tests PASSED** (URL resolution, pool config, lazy init, transactions, Alembic lifecycle, speaker schema, user-speaker mapping schema & rollback) |
| **Speaker Repository Suite** | `.venv/bin/pytest tests/test_speaker_repository.py -v` | 0 | **12/12 tests PASSED** (CRUD, active filters, validation, duplicate rejection, rollback) |
| **Device Auth & Hardening Suite**| `.venv/bin/pytest tests/test_device_auth.py -v` | 0 | **30/30 tests PASSED** (HMAC, PSK, anti-replay, nonce ordering, ASGI limiter, CORS, rate limits) |
| **Auth Security Test Suite** | `.venv/bin/pytest tests/test_auth.py -v` | 0 | **22/22 tests PASSED** (token verification, RBAC, revocation, WS auth, identity binding) |
| **Auth Policy Unit Tests** | `.venv/bin/pytest tests/test_auth_policy.py -v` | 0 | **7/7 tests PASSED** (identity separation, RBAC, endpoints) |
| **Baseline API Test Suite** | `.venv/bin/pytest tests/test_api.py -v` | 0 | **35/35 tests PASSED** (baseline contracts, upload limits, challenge lifecycle) |
| **Model Inference** | `.venv/bin/python predict.py "processed_dataset/Zubair/Zubair_Enrollment_R01.wav"` | 0 | Identifies `Zubair` (Score: 0.8668, Margin: +0.6073) |
| **Evaluation Suite** | `.venv/bin/python evaluate.py` | 0 | 27/27 test samples correct (100% accuracy, Macro F1: 1.0) |
| **Threshold Calibration** | `.venv/bin/python tune_threshold.py` | 0 | Generates ROC/DET curves; Genuine Mean: 0.8136, Impostor: 0.2520 |
| **Streamlit Smoke Test** | `streamlit.testing.v1.AppTest.from_file('app.py')` | 0 | AppTest initializes, runs with zero exceptions across 4 tabs |

---

## 4. Known Issues & Remaining Security Risks
1. **In-Memory Store & Rate Limiter Single-Process Boundary (`SEC-006`):**
   - *Risk:* `InMemoryChallengeStore`, `InMemoryNonceStore`, and `InMemoryRateLimiter` are process-local. Running Uvicorn with `--workers > 1` causes state divergence.
   - *Plan:* Replace with persistent storage (PostgreSQL/Redis) across subsequent database increments (Milestones 3C.3–3C.4).
2. **Pre-Shared Device Key Replay Limitation (`SEC-001` partial):**
   - *Status:* Constrained microcontrollers using Scheme B (`X-Device-Key`) lack application-layer replay resistance. Scheme A (HMAC-SHA256 with nonce and timestamp) is implemented and recommended for production terminals.
3. **Small Evaluation Dataset & Threshold Discordance (`SEC-009`):**
   - *Risk:* 0.00% EER is computed on only 3 speakers (27 test samples). Max impostor score of 0.6802 exceeds baseline threshold of 0.25.
   - *Plan:* Retain 0.25 for prototype compatibility; conduct comprehensive multi-session biometric evaluation before production.
4. **Voice Cloning Limitations (`SEC-010`):**
   - *Risk:* Spoken digit challenge-response mitigates static replay attacks, but does not defeat low-latency real-time generative voice cloning.

---

## 5. Next Recommended Step
Proceed to **Milestone 3C.2c.2: Persistent Authorization Enforcement**:
1. Implement database-backed user identity resolution querying `UserSpeakerMapping` in `app/core/device_auth.py` / `check_verification_authorization`.
2. Enforce that ordinary web users can verify only their bound speaker identity resolved from the database mapping.
3. Ensure administrative users can verify any speaker identity via established administrative policies.
4. Add authorization and regression tests covering mapped users, unmapped users, mismatched claimed identities, and admin overrides.
5. Push completed 3C.2c.2 increment to `feature/enterprise-foundation` before proceeding to Milestone 3C.3.




