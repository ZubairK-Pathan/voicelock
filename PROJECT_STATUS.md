# Project Status — VoiceLock Enterprise

**Last Updated:** October 22, 2026  
**Current Milestone:** Increment 2B — Administrator Identity Management UI (Completed)  
**Current Git State:** Branch `feature/enterprise-foundation`  
**Application Run Status:** Fully Operational (`voicelock-api` active on Azure Container Apps in `eastasia`; 119 frontend tests and 330 backend tests passing; 0 lint errors; clean production build; zero secret leakage; clean working tree)


---

## 1. Executive Status
Increment 5C replaces the prototype verification simulator in `frontend/src/components/pages/VerificationPage.tsx` with a real, end-to-end, API-driven voice verification flow. All fake scenario selectors (`genuine`, `impostor`, `spoof`), mocked success states, and client-side random digit generation were completely purged. The application now requests unpredictable, cryptographically generated spoken challenges from `POST /challenge`, presents the server digits with live 60-second TTL countdowns, captures genuine microphone audio via `useAudioRecorder`, provides waveform review and discard/re-record workflows, and submits real audio blobs with session and challenge bindings to `POST /verify`. Backend audio compatibility was established by adding `.webm` to `ALLOWED_EXTENSIONS` in `app/core/config.py` and `SUPPORTED_AUDIO_EXTENSIONS` in `audio_utils.py`, supported by FFmpeg's native Matroska/WebM demuxer and `libopus` decoder. Ordinary users without an authorized record in `UserSpeakerMapping` are presented with a clear, fail-closed access denial state explaining the administrative setup required, while administrators can verify enrolled speaker profiles retrieved live from `GET /speakers`. 12 automated tests in `frontend/src/components/pages/VerificationPage.test.ts` and new backend tests in `tests/test_api.py` validate all challenge display, recording, multipart submission, liveness rejection, impostor denial, unmapped identity fail-closed, and zero-mock invariants. All 96 frontend tests and 304 backend tests pass with 0 linter warnings and a clean production build.

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

### Milestone 3C.2c.2: Persistent User-to-Speaker Authorization Enforcement (Completed)
- **UserSpeakerRepository (`app/repositories/user_speaker_repository.py`):**
  - Built dedicated repository encapsulating persistence and queries on `user_speaker_mappings`:
    - `create()`: Maps user to speaker; validates inputs; enforces 1-to-1 uniqueness and foreign keys via `DuplicateUserMappingError`.
    - `get_by_firebase_uid()`: Retrieves mapping by Firebase UID.
    - `get_speaker_id_for_user()`: Fast scalar query returning bound `speaker_id`.
    - `get_by_speaker_id()`: Retrieves mapping by speaker ID.
    - `get_or_raise()`: Resolves mapping or raises `UserMappingNotFoundError`.
    - `delete_by_firebase_uid()` / `delete_by_speaker_id()`: Clean removal.
    - `list_mappings()` and `count()`: Pagination and record aggregation.
  - Re-exported in `app/repositories/__init__.py` and `app/db/__init__.py`.
  - Added 10 unit tests in `tests/test_user_speaker_repository.py`.
- **Database-Backed Identity Resolution & Authorization (`app/core/device_auth.py`):**
  - Refactored `resolve_user_voice_identity()` to query `UserSpeakerMapping` in the database where `firebase_uid == user.uid`.
  - Removed client-controlled fallback heuristics (no reliance on `user.voice_identity`, email prefix, or raw `user.uid`).
  - Refactored `check_verification_authorization()`:
    - Admin: Authorized for any registered speaker under explicit server policy.
    - Device: Authorized for any registered speaker at this physical portal.
    - Ordinary User: Authorized ONLY if mapped in `user_speaker_mappings` to the claimed speaker.
    - Unmapped users are rejected with HTTP 403 Forbidden.
    - Users attempting another speaker's identity are rejected with HTTP 403 Forbidden.
    - Database lookup errors fail closed with HTTP 500 (`Database authorization service unavailable.`).
- **Endpoint Pipeline Integration:**
  - `POST /verify` (`app/api/routes_verification.py`): Injects `db: Session = Depends(get_db)` and validates authorization *before* audio persistence and ML inference.
  - `POST /challenge` (`app/api/routes_challenges.py`): Injects `db: Session = Depends(get_db)` and validates/resolves user-speaker identity binding.
- **Dedicated Security Test Suite (`tests/test_persistent_auth.py`):**
  - Added 9 targeted tests covering:
    1. Mapped user verifying own identity.
    2. Unmapped user denied.
    3. User attempting different speaker identity denied.
    4. Client-supplied UID or role cannot override verified principal.
    5. Admin allowed according to explicit policy.
    6. Database lookup failure denies access (Fail closed).
    7. Authorization rejection happens before audio persistence and ML inference.
    8. Existing device-auth behavior remains correct.
    9. Existing challenge and verification behavior does not regress.
  - Total automated tests expanded to 140 passing tests in 2.74s.

### Milestone 3C.3a: Device Registry Schema and Migration (Completed)
- **DeviceRecord Model (`app/db/base.py`):**
  - Implemented `DeviceRecord` entity mapping to `devices` table using SQLAlchemy 2.0 declarative syntax:
    - `id`: Autoincrement integer primary key.
    - `device_id`: Unique, indexed, non-null `String(64)` identifying the physical access terminal.
    - `name`: Nullable `String(128)` describing the device name or physical installation location.
    - `status`: Lifecycle status (`String(32)`, default `"active"`, non-null) supporting `"active"`, `"suspended"`, and `"revoked"`.
    - `secret_hash`: `String(255)` storing one-way cryptographic hash / derived secret verifier (e.g. SHA-256 or PBKDF2). Raw pre-shared keys and HMAC secrets are strictly forbidden from database persistence.
    - `key_version`: Non-null `Integer` (default 1) enabling version tracking for zero-downtime key rotation in future increments.
    - `created_at` / `updated_at`: Timezone-aware UTC timestamps tracking device lifecycle.
    - `metadata_json`: Nullable `Text` for auxiliary device configuration (e.g., MAC address, firmware version, building zone).
    - `@property is_active`: Boolean check evaluating `self.status == "active"`.
  - Re-exported in `app/db/__init__.py` and `app/core/database.py`.
  - Sensitive data exclusion: strictly avoids storing plaintext secrets, Firebase tokens, biometric audio, or embedding vectors.
- **Alembic Migration (`316dea338f3b_create_devices_table.py`):**
  - Chained cleanly to revision `0b98eaf9dc3e` (`create_user_speaker_mappings_table`).
  - Implemented `upgrade()` and `downgrade()` managing table creation, unique index on `device_id`, and clean teardown.
- **Automated Schema & Rollback Tests (`tests/test_database.py`):**
  - Added `test_devices_schema_migration_and_constraints`:
    - Verifies migration upgrade to head, table column inspection, and unique index existence (`ix_devices_device_id`).
    - Validates valid insertion, field persistence, and `is_active` lifecycle transitions (`active` -> `revoked`).
    - Enforces uniqueness: duplicate `device_id` raises `IntegrityError`.
    - Validates single-revision rollback (`316dea338f3b -> 0b98eaf9dc3e`) dropping `devices` while preserving `user_speaker_mappings`, `speakers`, and `schema_initializations`.
    - Verifies re-application of `upgrade head`.
  - Total automated tests expanded to 141 passing tests in 2.95s.

### Milestone 3C.3b: Persistent Device Repository (Completed)
- **DeviceRepository (`app/repositories/device_repository.py`):**
  - Implemented data access repository for `DeviceRecord` entities using SQLAlchemy 2.0:
    - `create()`: Creates and persists a new `DeviceRecord`; validates non-empty `device_id` and `secret_hash`, allowed `status` (`active`, `suspended`, `revoked`), positive `key_version`; flushes to detect constraint violations; wraps duplicate errors in `DuplicateDeviceError`.
    - `get_by_device_id()`: Retrieves a device record by stable unique `device_id`.
    - `get_by_id()`: Retrieves a device record by integer primary key.
    - `get_or_raise()`: Resolves a device record or raises `DeviceNotFoundError`.
    - `list_devices()`: Lists devices ordered alphabetically by `device_id`, supports pagination (`limit`/`offset`) and lifecycle status filtering.
    - `update()`: Updates permitted metadata (`name`, `metadata_json`) and lifecycle `status` with timestamp update; flushes without autocommit.
    - `revoke()`: Helper method transitioning a device to `status="revoked"`.
    - `delete()`: Deletes a device record and returns boolean status.
    - `count()`: Aggregates total devices with optional status filtering.
  - Transaction safety: operations perform `flush()` without autocommit, leaving transaction ownership to the caller.
  - Sensitive data exclusion: operates strictly on hashed credentials (`secret_hash`), never storing, accepting, returning, or logging raw secrets. Biometric audio, embeddings, and Firebase tokens are strictly excluded.
  - Re-exported in `app/repositories/__init__.py` and `app/db/__init__.py`.
- **Automated Unit Tests (`tests/test_device_repository.py`):**
  - Added dedicated test suite covering all 12 core requirements:
    1. Enforcement of non-null Session initialization (`ValueError`).
    2. Record creation with valid attributes and defaults.
    3. Input validation (empty IDs, empty secret hash, invalid status, invalid key version).
    4. Duplicate `device_id` rejection (`DuplicateDeviceError`).
    5. Retrieval by `device_id` and primary key integer ID.
    6. Missing device handling (`None` vs `DeviceNotFoundError`).
    7. Listing, pagination, and status filtering.
    8. Metadata updates, lifecycle status transitions, and updated timestamps.
    9. Revocation helper (`status="revoked"`).
    10. Deletion and idempotent missing deletion.
    11. Device counting with optional status filtering.
    12. Caller-controlled transaction rollback.
  - Total automated tests expanded to 153 passing tests in 3.00s.

### Milestone 3C.3c: Database-Backed Device Authentication Integration (Completed)
- **Database Device Authentication (`app/core/device_auth.py`):**
  - Integrated `DeviceRepository` and `DeviceRecord` into device authentication pipeline (`get_current_device` and `get_current_actor`):
    - `lookup_device_record()`: Queries `DeviceRecord` by `device_id` via `DeviceRepository`. Eagerly loads columns and expunges record before closing session context to prevent detached instance errors.
    - Lifecycle status enforcement: checks persistent `DeviceRecord.status` before authenticating:
      - `revoked`: Rejects immediately with HTTP 401 (`Device has been revoked.`).
      - `suspended`: Rejects immediately with HTTP 401 (`Device is suspended.`).
      - Inactive: Rejects with HTTP 401 (`Device is not active (status: ...)`).
    - Secret verifier validation (`verify_device_secret_hash`): Compares SHA-256 verifier in constant time against `secret_hash`, supporting both prefixed `sha256$<hex>` and raw hex digests.
    - Scheme A (HMAC-SHA256): Verifies request timestamp tolerance (300s window), nonce formatting, body SHA-256 digest, canonical signing string, and expected HMAC signature computed from provisioned signing secret verified against registered `secret_hash`. Constant-time signature verification strictly precedes atomic nonce recording in `InMemoryNonceStore`.
    - Scheme B (Pre-Shared Key): Verifies incoming `X-Device-Key` against `DeviceRecord.secret_hash` in constant time without requiring plaintext secret storage.
    - Production fail-closed enforcement: In production, missing database device records are strictly rejected with HTTP 401. Database connection/query errors fail closed with sanitized HTTP 500 (`Database device authentication service unavailable.`).
    - Privilege separation: Devices strictly receive `Role.DEVICE` and can never impersonate `Role.ADMIN` or `Role.USER`.
- **Dedicated Test Suite (`tests/test_device_auth_database.py`):**
  - Added 12 comprehensive security tests using disposable SQLite databases:
    1. Valid active registered device authenticating via HMAC-SHA256.
    2. Valid active registered device authenticating via standalone X-Device-Key against database `secret_hash`.
    3. Unknown device rejected with HTTP 401.
    4. Revoked device in database rejected with HTTP 401.
    5. Suspended device in database rejected with HTTP 401.
    6. Invalid HMAC signature on registered device rejected with HTTP 401.
    7. Replayed nonce attack on registered device rejected with HTTP 401.
    8. Stale timestamp outside 300s drift window rejected with HTTP 401.
    9. Database lookup failure fails closed with HTTP 500.
    10. Privilege separation: Device permitted on `/challenge`, denied on `/speakers`.
    11. Mismatched secret hash rejected with HTTP 401.
    12. Secrets hygiene: Database record stores only one-way cryptographic hash, never plaintext.
  - Total automated tests expanded to 165 passing tests in 3.22s.

### Milestone 4A: React Frontend Foundation & Dashboard Prototype (Completed)
- **Scaffolding & Architecture (`./frontend`):**
  - Scaffolded modern standalone web client using React 19, TypeScript 6, and Vite 8 in `./frontend`, alongside the FastAPI backend and Streamlit reference app.
  - Implemented bespoke enterprise dark mode design system (`frontend/src/index.css`) with custom CSS variables, glassmorphism cards, Inter/JetBrains Mono typography, custom scrollbars, and accessible contrast.
  - Configured root and frontend `.gitignore` rules to exclude `frontend/node_modules/`, `frontend/dist/`, and local files.
- **Components & Navigation Architecture:**
  - `Layout`: Persistent responsive sidebar navigation with real-time badge counts, operational status indicator, and dynamic breadcrumbs.
  - `OverviewPage`: Primary telemetry grid (speakers, terminals, success rate, critical alerts), calibrated biometric model bar (0.25 threshold gauge, ECAPA-TDNN mean scores), threat alerts panel, and recent biometric verifications table.
  - `SpeakersPage`: Searchable, filterable identity table (All, Active, Suspended, Revoked) across all 12 registered speakers, 192-dim vector preview modal, and clearly labelled prototype enrollment placeholder.
  - `VerificationPage`: Interactive biometric verification simulator featuring:
    - Target terminal & speaker selection.
    - Dynamic CSPRNG 4-digit spoken challenge generation with 60-second TTL countdown timer.
    - Simulated 16kHz PCM audio waveform visualization.
    - Selectable evaluation scenarios: Genuine User (score 0.8668 >= 0.25, PASS), Impostor Voice (score 0.1842 < 0.25, DENIED), and Spoof/Liveness Mismatch (burn challenge, SPOOF DETECTED).
    - Latency reporting (118ms) and relay actuation status.
  - `DevicesPage`: Physical access terminals table (ESP32 portals, locations, IP addresses, HMAC-SHA256 scheme, key versions, status) with detailed terminal modal and registration interface placeholder.
  - `SecurityEventsPage`: Comprehensive security audit log with severity filtering (`critical`, `high`, `medium`, `low`), search, and full event payload inspection modal.
- **Decoupled Mock Data Module (`frontend/src/data/mockData.ts`):**
  - Built typed, coherent mock data mirroring real VoiceLock domain entities (12 speakers from evaluation split, 5 hardware terminals, security event stream, and verification records) with explicit `isSimulated: true` metadata.
- **Engineering Quality & Verification:**
  - TypeScript strict typing across all interfaces and types (`frontend/src/types/index.ts`).
  - `npm run lint` (`oxlint`): 0 warnings, 0 errors.
  - `npm run build`: Production bundle built cleanly in 147ms (HTML 0.98 kB, CSS 8.24 kB, JS 299 kB).
  - Development server running on `http://127.0.0.1:5173/`, verified live in a browser session across all 5 navigation views and modals.
  - Zero regressions on backend test suite: 165/165 tests passing.


### Milestone 4B: Firebase Authentication & Frontend Session Management (Completed)
- **Firebase Web SDK Architecture (`frontend/src/lib/firebase.ts`):**
  - Modular client SDK integration loading web configuration via Vite environment variables (`VITE_FIREBASE_*`).
  - Validation helper `isFirebaseConfigured()` preventing duplicate initialization and safely falling back to local demonstration mode when web configuration is unpopulated.
  - Sanitized template created in `frontend/.env.example` with zero secrets committed.
  - Root and frontend `.gitignore` updated to guarantee all local `.env*` files remain strictly excluded, while anchoring Python build rules so `frontend/src/lib/` is cleanly tracked.
- **Session Management & Context (`frontend/src/context/`):**
  - `AuthContext` and `useAuth` hook managing real-time auth state via `onAuthStateChanged`.
  - Lazy initialization preventing flash of unauthorized dashboard content during session hydration.
  - Safe mapping of Firebase error codes (`auth/invalid-credential`, `auth/wrong-password`, `auth/user-not-found`, `auth/user-disabled`, `auth/too-many-requests`) into user-friendly messages without leaking internal traces.
  - Development demonstration mode enabling seamless local operator sign-in (`admin@voicelock.internal`, `zubair@voicelock.internal`) when `.env.local` is missing.
- **Authentication UI (`frontend/src/components/auth/SignInPage.tsx`):**
  - Responsive Obsidian-themed sign-in console with VoiceLock shield branding.
  - Email and password inputs, password visibility toggle, accessible labels, autofocus, and form validation.
  - Interactive Firebase Console setup guide with step-by-step instructions (authorized domains, provider activation, web app registration).
  - Integrated into `Header.tsx` displaying the authenticated operator profile badge and Sign Out button.
- **Authenticated API Client (`frontend/src/lib/apiClient.ts`):**
  - Standalone typed HTTP client configured with base URL from `VITE_API_BASE_URL`.
  - Automatically fetches fresh ID tokens via `user.getIdToken()` and attaches them as `Authorization: Bearer <ID_TOKEN>`.
  - Safe error handling for 401 Unauthorized and 403 Forbidden without leaking tokens or logging secrets.
  - Tested with dedicated unit tests in `frontend/src/lib/apiClient.test.ts` (6 tests passing).
- **Engineering Quality & Verification:**
  - `npm test` (Node 25 native test runner): **6/6 tests passed in 22ms**.
  - `npm run lint` (`oxlint`): **0 warnings, 0 errors** across 21 files.
  - `npm run build`: Production bundle compiled cleanly in 153ms.
  - Live dev server validated on `http://127.0.0.1:5173/` via automated browser testing (login, toggle, setup guide, dashboard access, sign-out transition).
  - Backend regression: **165/165 tests passing** in `pytest`.


### Increment 1A: Persistent Speaker Embedding Schema & Repository Integration (Completed)
- **Database Schema Migration (`alembic/versions/8046c184216a_add_embedding_json_to_speakers.py`):**
  - Added portable, nullable `embedding_json` (`sa.Text`) column to `speakers` table using batch alter mode for full SQLite and PostgreSQL portability.
  - Chained cleanly to migration head `316dea338f3b` with reversible `upgrade()` and `downgrade()`.
  - Updated `SpeakerRecord` entity mapping in `app/db/base.py`.
- **Validation & Serialization Layer (`app/core/embeddings.py`):**
  - Built `serialize_embedding` and `deserialize_embedding` supporting both NumPy arrays and sequences.
  - Strict dimensionality enforcement: requires exactly 192 elements (default for ECAPA-TDNN).
  - Strict validation: rejects NaN, positive/negative infinity, non-numeric values, booleans, and malformed JSON.
  - Conversion to `np.float32` preserving exact vector values without altering, re-centering, or normalizing.
  - Privacy preservation: biometric vector values and elements are strictly excluded from exception messages and logs.
- **Repository Data-Access Layer (`app/repositories/speaker_repository.py`):**
  - Updated `create()` and `update()` methods to support `embedding` (`np.ndarray`) and `embedding_json` (`str`).
  - Added `get_embedding(speaker_id)` returning `Optional[np.ndarray]`.
  - Added `set_embedding(speaker_id, embedding)` returning updated `SpeakerRecord`.
  - Preserved transaction contract: operations execute `session.flush()` without committing, ensuring caller ownership.
- **Automated Verification:**
  - Added `tests/test_embeddings.py` (17 unit tests) covering roundtrip conversion, cosine similarity preservation, NaN/Inf rejection, and privacy guarantees.
  - Added 8 unit tests in `tests/test_speaker_repository.py` (20/20 passing) covering embedding creation, retrieval, updates, and transaction rollback.
  - Added `test_speakers_embedding_schema_migration` in `tests/test_database.py` (17/17 passing) validating Alembic schema migration and single-revision rollback.
  - Full automated backend test suite expanded from 165 to **191 tests passing in 2.85s**.

### Increment 1B: Safe Speaker Database Seeder (Completed)
- **Safe Seeder CLI & Engine (`scripts/seed_speakers.py`):**
  - Imports 10 approved real speaker identities (`Advait`, `Amaan Ur Raheman`, `Krish`, `Omar`, `Parth`, `Shreyas`, `Umair`, `Zubair`, `abid`, `vikas`) from `speaker_profiles/profiles.pkl` using `SpeakerRecord` and `SpeakerRepository`.
  - Filters out excluded non-approved identities (`abc`, `maam`) by default without renaming or inferring real identities.
  - Strict pre-write validation: validates dictionary structure, confirms all 10 approved keys exist, enforces 192-d numeric finite values (rejecting NaN, Inf, non-numeric), and verifies vector serialization.
  - Idempotency & conflict safety: identical existing records with active status and matching embeddings (`np.allclose`) are skipped without duplicate creation. Conflicting existing records (different embeddings, inactive status, or wrong dimension) trigger an immediate atomic rollback and non-zero exit without exposing biometric vectors.
  - Preserves caller-owned transaction semantics: all inserts commit atomically together or roll back completely on failure.
  - Grounded sample counts: `sample_count=21` for Advait, Omar, Parth based on sentence-disjoint reference split in `speaker_profiles/split_info.json`, and `sample_count=5` for the other 7 approved participants based on enrollment recordings in `processed_dataset/`.
  - CLI features: provides `--help`, `--dry-run` (validation and action reporting without persistent writes), and optional `--db-url` overrides, masking database credentials and suppressing vector values.
- **Automated Verification:**
  - Added `tests/test_seed_speakers.py` (17 unit tests) covering synthetic embedding seeding, sample count assignment, excluded identity filtering, strict validation, dry-run safety, rerun idempotency, conflict aborts, unrelated record preservation, midway failure rollbacks, Firebase isolation, unmigrated database detection, and CLI invocations.
### Increment 2: Database-Backed Speaker Service (Completed)
- **Database-Backed Service Architecture (`app/services/speaker_service.py`):**
  - Implemented `SpeakerService` operating strictly on caller-provided SQLAlchemy sessions (`Session`).
  - Implemented core query methods: `get_registered_speakers()`, `get_speaker_record()`, `is_speaker_active()`, `get_speaker_embedding()`, and `get_active_profiles()`.
  - Defined explicit typed exceptions: `SpeakerServiceError`, `SpeakerNotFoundError`, `InactiveSpeakerError`, `MissingSpeakerEmbeddingError`, `EmptySpeakerRegistryError`, and `SpeakerServiceDatabaseError`.
  - Reused `app.core.embeddings` (`deserialize_embedding`) for validating 192-d unit vectors and safely excluding corrupted or missing embeddings without crashing.
  - Implemented thread-safe SpeechBrain ECAPA-TDNN singleton cache (`get_classifier()`, `set_classifier_for_testing()`, `reset_classifier_for_testing()`).
  - Eliminated fallback to `speaker_profiles/profiles.pkl` in production API endpoints, failing closed with clean HTTP status codes (503 on empty registry, 500 on database failure).
- **FastAPI Endpoint Integration:**
  - `GET /speakers`: injected `db: Session = Depends(get_db)`, retrieving registered speakers from database.
  - `POST /challenge`: validates speaker presence and active status before issuing liveness challenge (HTTP 404 on unknown/inactive speaker).
  - `POST /identify`: performs 1-to-N identification against active database profiles under concurrency control (HTTP 503 on empty registry).
  - `POST /verify`: performs 1-to-1 verification against target database profile embedding, enforcing actor authorization and single-use challenge burn before disk writes and ML inference.
  - `WS /ws/identify`: identifies speakers against active database profiles using short-lived session context.
- **Workflow & Evaluation Preservation:**
  - Preserved standalone CLI and ML workflows (`predict.py`, `evaluate.py`, `tune_threshold.py`, `app.py`) and left pickle files untouched.
### Increment 3A: React Speakers Page Real API Integration (Completed)
- **Frontend Real Database Integration (`frontend/src/components/pages/SpeakersPage.tsx`):**
  - Connected `SpeakersPage` to FastAPI `GET /speakers` endpoint via `apiClient.getSpeakers()`, replacing all mock data entities (`MOCK_SPEAKERS`).
  - Reused the existing Firebase ID token provider in `App.tsx` and `apiClient.ts` to attach `Authorization: Bearer <ID_TOKEN>` headers.
  - Strictly adapted UI to the backend response schema (`registered_speakers: string[]`, `count: number`).
  - Omitted all fabricated fields: removed mock departments, fake enrollment dates, simulated sample counts, and fake clearance tiers.
  - Removed speaker creation controls, deletion controls, and embedding-editing mock modals.
  - Implemented comprehensive state machine:
    - **Loading State:** Centered card with spinning indicator and descriptive database querying copy.
    - **Empty State:** Distinct informative card displayed when the persistent database contains 0 registered speakers.
    - **Search Empty State:** Table empty row with clear search action when query filters out all identities.
    - **Error Handling (401 Unauthorized):** Amber warning banner explaining session expiry with re-authentication retry.
    - **Error Handling (403 Forbidden):** Rose security banner explaining that administrative role is required to enumerate the speaker registry.
    - **Error Handling (500 / Network Error):** Sanitized connection error banner with manual retry button.
    - **Success State:** Searchable table with live database counter, row indexing, active status badge, and ECAPA-TDNN 192-d architecture indicator.
- **Automated Verification:**
  - Added `frontend/src/lib/speakersService.test.ts` (9 tests) covering token attachment, real API response parsing, empty database handling, 401 expired sessions, 403 forbidden access, 500 database errors, network failures, search filtering, and zero-mock invariant verification.
  - Frontend test suite expanded from 6 to **15 tests passing in 142ms**.
  - Frontend production build (`npm run build`) passed cleanly in 98ms.
  - Frontend linter (`npm run lint`) reported **0 warnings and 0 errors** across 25 files.
  - Backend automated test suite remains 100% passing (**226/226 tests passing in 5.26s**).

### Increment 3B: Overview Dashboard Real Backend Metrics Integration (Completed)
- **Frontend Real Telemetry & State Management (`frontend/src/components/pages/OverviewPage.tsx`):**
  - Replaced hardcoded `MOCK_METRICS`, `MOCK_VERIFICATION_RECORDS`, and `MOCK_SECURITY_EVENTS` with dynamic queries to live backend endpoints via `apiClient.getSpeakers()` and `apiClient.getDevices()`.
  - Registered Speakers card dynamically renders live database count (`count`), displaying appropriate state messages: loading ("Querying biometric registry..."), empty database ("0 enrolled profiles (Database empty)"), unauthenticated ("Session unauthenticated"), or administrative restricted ("Admin authorization required"). Omitted fabricated monthly trend.
  - Access Terminals card connects to live hardware device registry via `GET /devices`, displaying total and active online counts (`${active} online of ${total} registered units`) or clean awaiting provisioning status ("0 terminals registered (Awaiting provisioning)"). Omitted fabricated suspended trend.
  - Verification Success Rate honestly renders uninstrumented state (`—`, "Audit log persistence not initialized") with a `Telemetry Offline` status badge.
  - Security Incidents honestly renders uninstrumented state (`—`, "Security event journal uninstrumented") with a `Telemetry Offline` status badge.
  - Added an explicit **Security Disclosure Notice** clarifying that the absence of logged incidents indicates uninstrumented event storage rather than zero threat activity or zero-failure operation.
  - Replaced simulated verification attempt rows with an honest "Biometric Access Journal Uninstrumented" empty-state panel pointing operators to the interactive verification console.
  - Biometric Model Calibration card cleanly presents verified offline baseline parameters (0.2500 server threshold, 0.8136 genuine mean, 0.2520 worst impostor, 192-d ECAPA, 16kHz mono).
- **Backend Terminal Registry Endpoint (`app/api/routes_devices.py`):**
  - Implemented `GET /devices` endpoint querying `DeviceRepository(db)` for `list_devices()`, `count()`, and `count(status="active")`.
  - Strict administrative authorization: enforced via `get_current_admin` (`Role.ADMIN` with `check_revoked=True`). Ordinary users are rejected with HTTP 403 Forbidden.
  - Strict data minimization: `secret_hash`, raw secrets, and tokens are completely excluded from the response schema (`DeviceItem`, `DevicesResponse`).
  - Declared `Permission.DEVICES_LIST` and registered route policy in `app/core/auth_policy.py`.
- **Top-Level Navigation Telemetry Sync (`frontend/src/App.tsx`, `Layout.tsx`, `Sidebar.tsx`):**
  - Updated `App.tsx` to dynamically query live speaker and device counts for sidebar badges, eliminating mock count fallbacks.
  - Updated `SidebarProps` and `LayoutProps` to support optional telemetry counts without rendering false badges.
- **Automated Verification:**
  - Added `tests/test_devices_api.py` (8 backend tests) verifying admin RBAC, data minimization, status filtering, unauthenticated requests, forbidden users, and database error handling.
  - Added `frontend/src/lib/overviewMetrics.test.ts` (8 frontend tests) verifying real metric loading, data minimization, 401/403/500/network error states, empty database handling, and zero-mock invariant compliance.
  - Total backend automated test suite expanded from 226 to **234 tests passing in 5.31s**.
  - Total frontend automated test suite expanded from 15 to **23 tests passing in 154ms**.
  - Frontend production build (`npm run build`) passed cleanly in 173ms with **0 warnings and 0 errors** on 26 files in `oxlint`.

### Increment 3C.1: Persistent Verification Event Schema (Completed)
- **Database Model & Enums (`app/db/base.py`, `app/db/__init__.py`, `app/core/database.py`):**
  - Created `VerificationOutcome` string enumeration defining bounded outcome states directly mapped from verification route execution paths: `verified` (similarity >= threshold + liveness passed), `rejected` (similarity < threshold), `challenge_failed` (spoken digits mismatch/silence/consumed), `unauthorized` (RBAC violation/speaker mismatch), and `error` (audio decode/runtime failure).
  - Defined `VerificationEvent` declarative model in `app/db/base.py`:
    - Columns: `id` (PK integer autoincrement), `created_at` (timezone-aware UTC DateTime, indexed), `outcome` (String(32), indexed, check constraint validated), `verification_flow` (String(32), default "web", validated), `user_id` (String(128) nullable, indexed), `speaker_id` (String(64) nullable FK, indexed), `device_id` (String(64) nullable FK, indexed), `request_id` (String(64) nullable, indexed).
    - Composite index: `ix_verification_events_created_outcome` on `(created_at, outcome)` for efficient time-windowed security dashboard metrics.
    - Check constraints: `ck_verification_events_outcome` and `ck_verification_events_flow`.
    - Referential integrity: `speaker_id` and `device_id` foreign keys enforce `ondelete="SET NULL"`, preserving audit trail history while decoupling orphaned entity IDs upon deletion.
    - Strict data minimization: Zero persistence of raw audio, audio paths, 192-d vectors, similarity scores, passwords, bearer tokens, or device secrets.
    - Re-exported symbols in `app.db` and `app.core.database`.
- **Alembic Migration (`alembic/versions/d0199d309a47_create_verification_events_table.py`):**
  - Chained revision `d0199d309a47` to `down_revision = '8046c184216a'`.
  - Implemented symmetric `upgrade()` creating `verification_events` table, foreign keys, check constraints, and 7 indexes.
  - Implemented clean `downgrade()` dropping all indexes and dropping `verification_events`.
- **Automated Verification:**
  - Added 4 comprehensive tests to `tests/test_database.py`:
    - `test_verification_event_model_creation_and_attributes`: defaults, UTC timezone-aware timestamps, enum mapping.
    - `test_verification_event_outcome_and_flow_validation`: validates strict bounded outcome and flow rejection of invalid/empty values.
    - `test_verification_events_schema_migration_and_constraints`: migration execution, column/index inspection, composite index query verification, and single-revision rollback.
    - `test_verification_events_foreign_key_set_null_on_delete`: verifies audit preservation with `ON DELETE SET NULL` when speakers or devices are deleted.
  - Database test suite expanded from 17 to **21 tests passing in 1.05s**.
  - Total backend automated test suite expanded from 234 to **238 tests passing in 5.32s**.
  - Verified clean frontend suite (**23/23 tests passing**, 0 lint errors, build passing in 182ms).
  - ML sanity check verified (ECAPA-TDNN CPU inference score: 0.8668).

### Increment 3C.2: Verification Event Repository (Completed)
- **Repository Implementation (`app/repositories/verification_event_repository.py`, `app/repositories/__init__.py`, `app/db/__init__.py`):**
  - Created `VerificationEventRepository` encapsulating all persistence, retrieval, and aggregate logic for `VerificationEvent` entities.
  - Enforced caller-controlled transaction semantics: all methods add entities and flush to expose database-generated primary keys without calling `commit()` or `rollback()`.
  - Implemented `create_event(...)` validating outcomes against `VALID_VERIFICATION_OUTCOMES` and flows against `VALID_VERIFICATION_FLOWS`, stripping whitespace from identifiers, handling timezone-aware UTC timestamps, and flushing the entity.
  - Implemented `get_event(...)` and `get_or_raise(...)` (raising `VerificationEventNotFoundError` on missing ID).
  - Implemented `list_events(...)` with bounded pagination (1 to 500, non-negative offset), deterministic newest-first ordering (`created_at DESC, id DESC`), and optional filters: outcome, verification_flow, user_id, speaker_id, device_id, and time window `[start_time, end_time)` in UTC.
  - Implemented `count_events(...)` using database `func.count(id)` aggregates matching all optional filters and time windows.
  - Implemented `count_by_outcome(...)` computing grouped outcome counts over an optional `[start_time, end_time)` time window, guaranteeing all 5 valid outcome states are returned with counts $\ge 0$.
  - Strictly enforced the `[start_time, end_time)` (start inclusive, end exclusive) UTC interval convention across all query methods, rejecting invalid date ranges (`start_time > end_time`) with `ValueError`.
  - Re-exported `VerificationEventRepository`, `VerificationEventRepositoryError`, and `VerificationEventNotFoundError` in `app.repositories` and `app.db`.
- **Automated Verification:**
  - Added dedicated unit test suite in `tests/test_verification_event_repository.py` (13 tests):
    - Non-null session requirement.
    - Minimal event creation and generated ID.
    - Full identity and timestamp creation with `VerificationOutcome` enum.
    - Caller-controlled transaction rollback semantics.
    - Retrieval of existing and missing IDs (`get_event` and `get_or_raise`).
    - Pagination, offset, and deterministic newest-first ordering.
    - Pagination boundary validations (`limit < 1`, `limit > 500`, `offset < 0`).
    - Outcome and verification flow filtering.
    - Strict `[start_time, end_time)` UTC boundary tests (start inclusive, end exclusive).
    - Invalid date range rejection.
    - Aggregate `count_events` on empty and populated databases with filters.
    - Grouped `count_by_outcome` aggregates over time windows and flow filters.
    - Input validation on invalid outcomes and flows.
  - Total backend automated test suite expanded from 238 to **251 tests passing in 5.41s**.
  - Total frontend automated test suite remains 100% passing (**23/23 tests passing**, 0 lint errors, build passing in 178ms).

### Increment 3C.3: Persist Verification Outcomes (Completed)
- **Verification Route Event Instrumentation (`app/api/routes_verification.py`):**
  - Integrated `VerificationEventRepository` with `POST /verify` request flow to persist real biometric access outcomes into the `verification_events` database table.
  - Defined explicit lifecycle state transitions:
    - **Pre-attempt boundary:** Requests rejected before challenge consumption (401 unauthenticated, 429 rate limit, 400 empty claimed identity, 503 no enrolled speakers, 404 unregistered/inactive speaker, 403 user-speaker unauthorized, 400 missing/expired/reused challenge) do NOT create misleading verification events.
    - **Attempt initiation:** Challenge is consumed atomically (`store.validate_and_consume`), establishing the start of the verification attempt and enforcing burn-on-use replay protection.
    - **Challenge failure (`challenge_failed`):** Spoken digit STT liveness evaluation fails (`is_live=False`); persists `challenge_failed` event, rolls back on commit failure without overriding HTTP response, and denies access (`action="DENY"`) without running ML inference.
    - **Biometric rejection (`rejected`):** Spoken liveness passes but ECAPA-TDNN similarity is below calibrated server threshold; persists `rejected` event and returns denial (`action="DENY"`).
    - **Biometric acceptance (`verified`):** Spoken liveness passes and ECAPA-TDNN similarity meets/exceeds calibrated server threshold; persists `verified` event and returns access grant (`action="UNLOCK"`).
    - **Processing failure (`error`):** Audio decoding failure (`sf.LibsndfileError`, `ValueError`), FFmpeg conversion error (`RuntimeError`), or ML inference runtime exception; persists `error` event and returns appropriate sanitized error (400/500).
  - **Transaction & Failure Policy:**
    - `VERIFIED`: High-assurance non-repudiation requires persistent audit logging before granting physical or logical access (`action="UNLOCK"`). If `db.commit()` fails on a verified outcome, the system rolls back and fails closed (`HTTPException(500, detail="Database failure recording verification audit trail.")`). Access is strictly NOT granted.
    - `REJECTED` & `CHALLENGE_FAILED`: Access is already denied (`action="DENY"`). If `db.commit()` fails, the session is rolled back, a warning is logged, and the client's denial response is preserved without exposing database failure or masking the rejection.
    - `ERROR`: Preserves the underlying client/processing error response (e.g. HTTP 400 for bad audio). If `db.commit()` fails, the session is rolled back, a warning is logged, and the original exception is preserved.
  - **Guarantees & Invariants:**
    - **At-most-once attempt recording:** Implemented `event_recorded` execution flag ensuring every consumed attempt creates at most one database event even across exception handlers.
    - **Trusted identity binding:** `user_id` bound only from authenticated Firebase actor (`actor.uid`); `device_id` bound only from authenticated terminal (`actor.device_id`); `verification_flow` set to `"device"` for IoT terminals and `"web"` for browser users; `speaker_id` bound only from validated, authorized speaker identity.
    - **Correlation ID propagation:** Sanitizes and propagates `X-Request-ID` or `X-Correlation-ID` headers up to 64 characters; defaults safely to `None`.
    - **Zero sensitive data leakage:** Zero raw audio bytes, audio paths, 192-d embeddings, similarity scores, bearer tokens, passwords, or device keys persisted.
- **Automated Verification:**
  - Added comprehensive test suite in `tests/test_verification_route_audit.py` (15 tests):
    - Successful verification records exactly one `verified` event with complete metadata.
    - Biometric rejection records exactly one `rejected` event.
    - Spoken liveness failure records exactly one `challenge_failed` event without running inference.
    - Device verification records `verification_flow="device"` and `device_id`.
    - Corrupt audio decoding failure records `error` event with HTTP 400.
    - ML inference exception records `error` event with HTTP 500.
    - FFmpeg conversion failure records `error` event with HTTP 400.
    - Unauthenticated request (401) records 0 events.
    - Unauthorized cross-speaker request (403) records 0 events.
    - Pre-attempt rejections (missing/expired challenge, missing speaker) record 0 events.
    - Verified outcome commit failure fails closed with HTTP 500.
    - Rejected outcome commit failure preserves denial HTTP response.
    - Correlation ID truncation and sanitization (>64 chars).
    - Zero sensitive data persisted in event records.
    - Burn-on-use replay protection: replaying consumed challenge returns 400 and creates no second event.
  - Total backend automated test suite expanded from 251 to **266 tests passing in 6.28s**.
  - Total frontend automated test suite remains 100% passing (**23/23 tests passing**, 0 lint errors, build passing in 186ms).
  - ML sanity check verified (ECAPA-TDNN CPU inference score: 0.8668).

### Increment 3C.4: Admin Verification Metrics API (Completed)
- **Admin Verification Metrics Endpoint (`app/api/routes_metrics.py`):**
  - Implemented `GET /metrics/verification` and `GET /metrics` alias routes exposing aggregate biometric verification metrics from the persistent `VerificationEvent` journal.
  - Exclusively queries aggregates via `VerificationEventRepository.count_by_outcome(...)` adhering strictly to request-scoped database sessions and caller-controlled transactions (zero repository commits).
  - Returns structured, documented JSON schema (`VerificationMetricsResponse`):
    - `total`: Total recorded verification events matching filters.
    - `verified`: Accepted biometric verifications.
    - `rejected`: Rejected biometric comparisons below threshold.
    - `challenge_failed`: Spoken digit challenge failures.
    - `error`: Processing, media decoding, or runtime errors.
    - `success_rate`: Biometric verification success percentage.
    - `start_time` / `end_time`: Normalized UTC window boundaries (if queried).
    - `verification_flow`: Filter applied (`web` or `device`, or `None`).
  - **Explicit Success Rate Denominator:**
    - Formula: `verified / (verified + rejected + challenge_failed) * 100.0` (rounded to 2 decimal places).
    - Processing errors (`error`) represent media transport or system faults rather than biometric decisions and are explicitly excluded from the denominator.
    - When `verified + rejected + challenge_failed == 0`, the endpoint returns `0.0` safely avoiding division by zero.
  - **Time Window & Flow Filtering:**
    - Supports bounded UTC time window filtering adhering to the `[start_time, end_time)` start-inclusive, end-exclusive convention.
    - Validates that `start_time <= end_time` (returns HTTP 400 with clear message on invalid window).
    - Supports `verification_flow` query parameter, validating against `VALID_VERIFICATION_FLOWS` (returns HTTP 400 on invalid flow).
  - **Administrative Authorization & Security Boundaries:**
    - Requires server-side Firebase authentication and administrative RBAC (`admin: AuthenticatedUser = Depends(get_current_admin)` with `check_revoked=True`).
    - Declared `Permission.METRICS_READ = "metrics:read"` in `app/core/auth_policy.py`, assigned to `Role.ADMIN`, and mapped in `ENDPOINT_POLICIES`.
    - Strictly rejects unauthenticated requests (HTTP 401), ordinary users with `Role.USER` (HTTP 403 Forbidden), device identities (HTTP 401), and expired/revoked tokens (HTTP 401).
  - **Strict Data Minimization Guarantee:**
    - Exposes only aggregate counts and percentages.
    - Never leaks raw event records, individual attempt timestamps, user IDs, speaker IDs, device IDs, request IDs, audio files, embeddings, or similarity scores.
  - **Fail-Closed Error Handling:**
    - Catches database errors and returns sanitized HTTP 500 without leaking stack traces or SQL details.
- **Automated Verification:**
  - Added dedicated test suite in `tests/test_metrics_api.py` (14 tests):
    - Admin access succeeds on `/metrics/verification` and `/metrics` returning 200 with schema.
    - Unauthenticated requests return HTTP 401.
    - Ordinary user tokens (`Role.USER`) return HTTP 403 Forbidden.
    - Device headers without admin token return HTTP 401.
    - Expired and revoked tokens return HTTP 401.
    - Empty database returns all zeros (`total: 0`, `success_rate: 0.0`).
    - Mixed outcomes and exact success-rate denominator (5 verified, 3 rejected, 2 challenge_failed, 4 error -> total 14, denominator 10, success_rate 50.0%).
    - Zero biometric attempts with errors returns `success_rate: 0.0` without division by zero.
    - Bounded UTC time-window filtering (`[start, end)` inclusive-exclusive).
    - Inverted time window (`start_time > end_time`) returns HTTP 400.
    - Verification flow filtering isolates `web` vs `device`.
    - Invalid flow returns HTTP 400.
    - Data minimization: asserts sensitive IDs, embeddings, and similarity scores are completely absent from response.
    - Fail-closed database failure returns sanitized HTTP 500.
  - Updated `tests/test_auth_policy.py` verifying `Permission.METRICS_READ` assignment and endpoint policy discovery.
  - Total automated backend test suite expanded from 266 to **280 tests passing in 7.01s**.
  - Total frontend automated test suite remains 100% passing (**23/23 tests passing**, 0 lint errors, build passing in 193ms).
  - ML inference sanity check passed (ECAPA-TDNN score: 0.8668).

### Increment 3C.5: Connect React Overview to Real Verification Metrics (Completed)
- **API Client Method & Interface (`frontend/src/lib/apiClient.ts`, `frontend/src/types/index.ts`):**
  - Added typed method `getVerificationMetrics(params?, options?)` to `ApiClient`, querying `GET /metrics/verification` with optional query parameters (`start_time`, `end_time`, `verification_flow`).
  - Automatically attaches Firebase ID Bearer token via `Authorization: Bearer <ID_TOKEN>`.
  - Added TypeScript response interface `VerificationMetricsResponse` matching the FastAPI backend schema exactly (`total`, `verified`, `rejected`, `challenge_failed`, `error`, `success_rate`, `start_time`, `end_time`, `verification_flow`).
- **Overview Dashboard Integration (`frontend/src/components/pages/OverviewPage.tsx`):**
  - **Verification Success Rate Card:**
    - Displays backend-calculated `success_rate.toFixed(1)%` from persistent verification events.
    - Accurately renders genuine zero-valued responses as `0.0%` with subtitle `"0 attempts recorded (Journal empty)"`.
    - Correctly renders `"—"` with `"Querying verification telemetry..."` during loading and `"Telemetry unavailable"` on failure (avoiding false zeros).
    - Subtitle reports exact counts: `"{verified} verified of {evaluated} evaluated attempts"`.
    - Omits fabricated trends or arbitrary arrows from single aggregate snapshots.
  - **Biometric Verification Telemetry Breakdown Card:**
    - Provides real-time persistent outcome chips:
      - `Verified (Access Granted)` (Green accent, threshold >= 0.25)
      - `Biometric Rejected` (Red accent, similarity < 0.25)
      - `Challenge Failed (Spoof / STT)` (Amber accent, liveness digits unverified)
      - `Processing Errors` (Slate accent, audio decode / server faults)
    - Clearly documents the success rate denominator in the footer note: `verified / (verified + rejected + challenge_failed) * 100`, explaining that processing errors are excluded from biometric accuracy calculation.
    - Displays computed rate alongside total attempt badge.
  - **Loading, Auth, and Error Handling:**
    - Preserves synchronized `Promise.all` fetching of speakers, devices, and metrics.
    - Propagates 401 Unauthorized and 403 Forbidden statuses with clear explanatory banners.
    - Provides working `Retry Query` action on network or backend errors.
  - **Zero-Mock & Security Invariants:**
    - Zero usage or imports of mock metrics or fabricated records.
    - Preserves security incident card as uninstrumented (`Telemetry Offline`) and maintains the explicit security disclosure notice.
    - Maintains the uninstrumented recent activity stream placeholder pointing to the verification simulator.
- **Automated Verification:**
  - Added 8 automated unit tests in `frontend/src/lib/overviewMetrics.test.ts`:
    - Real metric loading with Bearer token authentication.
    - Time-window and flow query parameter serialization.
    - Genuine zero-valued metric response handling.
    - 401 Unauthorized handling without false zeros.
    - 403 Forbidden handling without false zeros.
    - 500 Database failure and network drop error propagation.
    - Data minimization check (absence of PII, raw IDs, audio, vectors).
    - OverviewPage source integration invariants.
  - Total frontend automated test suite expanded from 23 to **31 tests passing in 157ms** across 4 suites.
  - Frontend lint passing with 0 warnings, 0 errors across 26 files.
  - Frontend production build passed in 180ms.
  - Total backend automated test suite verified (280/280 tests passing in 7.83s).
  - ML inference sanity check passed (ECAPA-TDNN score: 0.8668).

### Increment 3D.1: Persistent Security Event Schema (Completed)
- **Database Model & Taxonomies (`app/db/base.py`, `app/db/__init__.py`):**
  - Defined `SecurityEvent` model in `app/db/base.py` for persistent enterprise security audit logging, completely independent of routine biometric verification attempts (`VerificationEvent`).
  - Controlled security event taxonomies:
    - `SecurityEventType`: `rate_limit_exceeded`, `payload_too_large`, `hmac_nonce_replay`, `hmac_signature_invalid`, `hmac_timestamp_skew`, `unknown_device_rejected`, `revoked_device_blocked`, `device_key_invalid`, `auth_token_expired`, `auth_token_revoked`, `auth_token_invalid`, `unauthorized_access`, `unauthorized_speaker_claim`, `admin_action`, `suspicious_payload`.
    - `SecurityEventSeverity`: `low`, `medium`, `high`, `critical`.
    - `SecurityEventStatus`: `blocked`, `detected`, `logged`, `resolved` (defaults to `blocked`).
  - Strict privacy and data minimization invariants:
    - Strictly excludes raw audio, 192-d biometric embeddings, similarity scores, bearer tokens, passwords, HMAC keys, signatures, and raw exception stack traces.
    - Excludes client IP addresses and user-agent strings by default.
    - Bounded string lengths: `details` ($\le 255$), `user_id` ($\le 128$), `device_id` ($\le 64$), `request_id` ($\le 64$).
    - Optional structured metadata (`metadata_json`) bounded to $\le 2048$ characters, parsed and validated as a JSON object, with active rejection of prohibited sensitive keys (`token`, `password`, `secret`, `secret_hash`, `key`, `hmac_key`, `signature`, `audio`, `embedding`, `similarity`, `similarity_score`, `ip`, `client_ip`, `user_agent`).
  - Referential integrity & audit trail preservation:
    - `device_id` references `devices.device_id` with `ondelete="SET NULL"`, preserving audit trails when registered terminals are deleted.
    - `user_id` stores external Firebase UID string without local cascading deletion.
  - Check constraints:
    - `ck_security_events_severity`: validates allowed severity values.
    - `ck_security_events_status`: validates allowed status values.
    - `ck_security_events_event_type`: validates allowed event type values.
  - Index strategy:
    - Single-column indexes on `created_at`, `event_type`, `severity`, `user_id`, `device_id`, `request_id`.
    - Composite indexes: `ix_security_events_created_severity` on `(created_at, severity)` and `ix_security_events_created_type` on `(created_at, event_type)` for efficient time-window security incident queries.
  - Re-exported `SecurityEvent`, enums, and sets in `app/db/__init__.py`.
- **Alembic Migration (`alembic/versions/ea5fe481812c_create_security_events_table.py`):**
  - Chained revision `ea5fe481812c` with `down_revision = 'd0199d309a47'`.
  - Implemented symmetric `upgrade()` creating `security_events` table, foreign keys, check constraints, and 8 indexes.
  - Implemented clean `downgrade()` dropping all indexes and dropping `security_events`.
- **Automated Verification:**
  - Added 6 comprehensive tests in `tests/test_database.py`:
    - `test_security_event_model_creation_and_defaults`: verifies instantiation, UTC timezone-aware default `created_at`, default `status="blocked"`, and optional attributes.
    - `test_security_event_validation_enums_and_taxonomy`: verifies strict bounded validation of event types, severities, and statuses, rejecting invalid or empty values.
    - `test_security_event_length_bounds_and_metadata_validation`: verifies length boundaries on `details`, `user_id`, `device_id`, `request_id`, and `metadata_json`, as well as JSON object structure.
    - `test_security_event_prohibited_metadata_keys`: verifies rejection of prohibited sensitive keys in metadata.
    - `test_security_events_schema_migration_and_constraints`: executes migration against disposable database, verifies reflected schema, inserts diverse events, executes composite and single filter queries, and tests single-revision downgrade to `d0199d309a47` and re-upgrade to `head`.
    - `test_security_events_foreign_key_set_null_on_device_delete`: verifies audit preservation with `ON DELETE SET NULL` when registered devices are deleted.
  - Database test suite expanded from 21 to **27 tests passing in 1.63s**.
  - Total automated backend test suite expanded from 280 to **286 tests passing in 7.38s**.
  - Frontend test suite remains clean (**31/31 tests passing**, 0 lint warnings, build passing in 190ms).
  - ML sanity check verified (ECAPA-TDNN score: 0.8668).

### Increment 4A: Production Containerization & Cloud Build Baseline (Completed)
- **Production Packaging & Hardening (`Dockerfile`, `.dockerignore`, `requirements.txt`):**
  - Added verified missing production dependency `firebase-admin>=7.0.0` to `requirements.txt`.
  - Created production `Dockerfile` (Python 3.11-slim) with non-root security:
    - Creates unprivileged group and user `voicelock` (UID 10001, GID 10001) and sets `USER voicelock`.
    - Installs OS-level audio transcoding tools (`ffmpeg`, `libsndfile1`) and HTTP probe utilities (`curl`, `ca-certificates`).
    - Leverages Docker layer caching: copies `requirements.txt` and installs dependencies prior to copying application source.
    - Pre-warms biometric and speech recognition models during build via `scripts/warmup_models.py`, baking SpeechBrain ECAPA-TDNN (~68MB) and Vosk STT (~40MB) directly into `/app/.model_cache/` to ensure the container is self-contained without runtime download dependencies or broken host symlinks.
    - Assigns `/app` ownership to `voicelock:voicelock`.
    - Defines container `HEALTHCHECK` probing `GET /` (`curl -f http://localhost:8000/ || exit 1`) with 30s interval, 5s timeout, and 30s cold-start grace period.
    - Runs production FastAPI application via `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
  - Created `.dockerignore` strictly excluding secrets (`firebase-credentials*.json`, `.env*`), raw audio datasets (`processed_dataset/`, `recordings/`, `*.wav`), local databases (`voicelock.db`, `*.sqlite*`), virtual environments (`.venv/`), `node_modules/`, local `.model_cache/` symlinks, and `frontend/` source (deployed separately to Static Web Apps).
  - Created `scripts/warmup_models.py` automating model cache initialization during container image builds.
- **Automated Verification:**
  - Added dedicated test suite in `tests/test_containerization.py` (4 tests):
    - `test_requirements_contains_production_dependencies`: verifies all core and production dependencies including `firebase-admin`.
    - `test_dockerfile_security_and_runtime_conventions`: verifies base image, non-root user, ffmpeg installation, warmup script execution, health probe, and uvicorn CMD.
    - `test_dockerignore_security_exclusions`: verifies all critical exclusions (credentials, audio, DBs, virtualenvs, local symlinks).
    - `test_warmup_models_script_structure`: verifies execution and importability of `scripts/warmup_models.py`.
  - Total automated backend test suite expanded from 286 to **290 tests passing in 6.86s**.
  - Frontend test suite remains clean (**31/31 tests passing**, 0 lint warnings, clean production build in 189ms).
  - Model warmup script verified locally (`scripts/warmup_models.py` exited with 0).
  - Note: Docker daemon is currently offline on local macOS developer host; local image build remains unverified until Docker Desktop is started or built via GitHub Actions runner.

### Increment 4B: Neon PostgreSQL Setup & Cloud Database Validation (Completed)
- **Neon Platform & CLI Integration:**
  - Configured project-level Neon MCP server for Antigravity using OAuth URL `https://mcp.neon.tech/mcp` without long-lived API keys.
  - Installed official Neon agent skills: `neon`, `neon-postgres`, `neon-ai-gateway`, `neon-functions`, `neon-object-storage`, `neon-postgres-branches`, `neon-postgres-egress-optimizer`, `neon-realtime`.
  - Linked to existing Neon project `sweet-block-01674817` (`org-proud-feather-80065126`), branch `production` (`br-withered-tree-b5mlkkc3`), AWS region `aws-us-east-2`.
  - Initialized `neon.ts` declaring `postgres` service and non-default branch auto-expiration policy.
  - Ran `neon deploy` successfully, pulling `DATABASE_URL` (pooled) and `DATABASE_URL_UNPOOLED` (direct) into `.env.local`.
- **Database Routing & Connection Practices:**
  - Added `.neon` to `.gitignore` and `.dockerignore`.
  - Enhanced `app/core/config.py` with zero-dependency `load_env_files()` to automatically load local `.env` and `.env.local` files without overwriting existing environment variables, while skipping automatic loading during `pytest` runs to keep test execution completely local, isolated, and fast.
  - Enhanced `app/db/session.py` with `get_migration_url()` prioritizing unpooled direct connections (`DATABASE_URL_UNPOOLED`) for Alembic migrations, preventing PgBouncer transaction-mode state, prepared statement leaks, and catalog lock issues.
  - Updated `alembic/env.py` to utilize `get_migration_url()`.
- **Live Schema Migration & Verification:**
  - Successfully executed all 7 Alembic migrations on live Neon PostgreSQL (`ea5fe481812c (head)`), creating tables:
    `alembic_version`, `schema_initializations`, `speakers`, `user_speaker_mappings`, `devices`, `verification_events`, `security_events`.
  - Verified live end-to-end repository queries over TLS (`SpeakerRepository`, `DeviceRepository`, `VerificationEventRepository`).
  - Verified live production-like Uvicorn server serving `GET /` returning `status: "online"`.
- **Automated Test Suite:**
  - Created `tests/test_neon_database.py` with 6 automated tests:
    - `test_neon_url_normalization`: dialect prefix normalization.
    - `test_neon_url_masking`: credential redaction.
    - `test_env_loading_preserves_existing_environment`: non-overwrite guarantee.
    - `test_migration_url_prioritizes_unpooled_connection`: unpooled migration routing.
    - `test_all_seven_alembic_migrations_present`: complete unbroken migration chain.
    - `test_live_neon_postgresql_connectivity`: live TLS connection, schema verification, and repository querying.
- **Biometric Privacy & Seeding Architecture Plan:**
  - Real speaker biometric profiles (`speaker_profiles/profiles.pkl`) were NOT uploaded or seeded into the remote database in this increment.
  - *Safe Seeding Plan:* A dedicated admin CLI script (`scripts/seed_remote_speakers.py`) will be executed by an authorized human operator with direct database access. The script will read local profiles, validate 192-d vectors, and insert records directly over encrypted TLS without ever committing profiles, keys, or audio to Git.

### Increment 4C: Docker Build and Runtime Validation (Completed)
- **Container Build & Offline Cache:**
  - Built local Linux Docker backend image `voicelock-api:local-test` on Docker Desktop (`linux/arm64`).
  - Configured non-root UID 10001 (`voicelock:voicelock`) with `HF_HOME=/home/voicelock/.cache/huggingface`, ensuring offline HuggingFace and Vosk caches are owned by the unprivileged user.
  - Verified container executes under UID 10001 on PID 1 with zero runtime model downloads.
- **Verification:**
  - Verified `HEALTHCHECK` passes on `GET /` (HTTP 200).
  - Added `tests/test_containerization.py` (4 tests).

### Increment 4D: Azure Deployment Readiness & Docker Image Optimization (Completed)
- **Image Optimization (79% Reduction):**
  - Optimized PyTorch installation by using CPU wheels (`--extra-index-url https://download.pytorch.org/whl/cpu`), stripping ~4.1 GB of unused CUDA and Triton binaries.
  - Optimized layer caching with `COPY --chown=voicelock:voicelock . .`.
  - Excluded raw datasets and pickle files via `.dockerignore`.
  - Reduced final container image size from 3.9 GB to 830 MB.
- **Production Audit & Cost Strategy:**
  - Confirmed fail-closed Firebase auth, CORS rejection of wildcards with credentials, and TLS database connectivity.
  - Authored Azure deployment readiness and cost strategy for Azure Container Apps + Azure Static Web Apps.

### Increment 4E: Live Database Container Validation & Azure Deployment Preparation (Completed)
- **Live Neon Container Validation:**
  - Validated optimized Docker container (`voicelock-api:readiness-test`) against live Neon PostgreSQL database (`sweet-block-01674817`) over TLS.
  - Verified container lifespan pre-warms all 10 active speaker profiles from the database and public discovery probe `GET /` returns HTTP 200 OK.
  - Hardened database connection URL parser in `app/db/session.py` to strip surrounding quotes from environment variables, with full test coverage in `tests/test_database.py`.
- **Runtime Telemetry & Sizing:**
  - Idle container memory footprint: 505.2 MiB (peak ~650–750 MiB during ML inference).
  - Idle CPU: 0.26%.
  - Verified Azure Container Apps sizing: 1.0 vCPU and 2.0 GiB RAM.
  - Verified container cold-start latency: 5–7 seconds from idle/cold to live response.
- **Azure & GHCR Architecture:**
  - Backend: Azure Container Apps consumption tier with scale-to-zero (`minReplicas = 0`, `maxReplicas = 1`) to guarantee $0.00/month recurring cost within Azure for Students monthly free grants (180,000 vCPU-seconds and 360,000 GiB-seconds free).
  - Frontend: Azure Static Web Apps Free tier ($0.00/month).
  - Container Registry: Private GitHub Container Registry (GHCR) with Personal Access Token (`read:packages`) stored as ACA secret, incurring $0 extra Azure costs.
  - Secret Mounting: Firebase service-account secret mounting via ACA secret volume or base64 environment variable without leaking credentials.
  - Verified 297 backend tests passing in 15.52s, 31 frontend tests passing in 156ms.

### Increment 4H: Frontend Google Sign-In with Firebase Popup & Role Resolution (Completed)
- **Google OAuth Integration:**
  - Exported configured `googleAuthProvider` in `frontend/src/lib/firebase.ts` with `{ prompt: 'select_account' }`.
  - Implemented `signInWithGoogle` using `signInWithPopup(auth, googleAuthProvider)` in `frontend/src/context/AuthContext.tsx`.
  - Maintained complete backwards compatibility with existing email/password authentication, ID-token acquisition, token refreshing, and session sign-out.
  - Implemented client-side demo fallback for local development without live Firebase credentials.
- **Role Derivation & Authorization:**
  - Integrated `resolveUserRole()` in `frontend/src/context/authUtils.ts` to assign `admin` role to `pzubair580@gmail.com` (matching backend `ADMIN_EMAILS` server-side allowlist) and accounts with custom token claims (`admin: true`, `role: 'admin'`).
  - Standard non-admin operators default to `user` role.
- **Enterprise Error Handling & User Interface:**
  - Mapped Firebase OAuth popup errors in `mapFirebaseError()`: `auth/popup-closed-by-user`, `auth/popup-blocked`, `auth/cancelled-popup-request`, `auth/account-exists-with-different-credential`, `auth/unauthorized-domain`.
  - Built branded Google Sign-In button in `frontend/src/components/auth/SignInPage.tsx` with official multicolor Google SVG icon, enterprise dark-theme styling, and clear visual separator.
- **Comprehensive Test Coverage & Quality Gates:**
  - Created automated test suite in `frontend/src/context/authUtils.test.ts` covering role resolution, error mapping, demo user profiles, GoogleAuthProvider options, simulated OAuth popup flow, token acquisition, session persistence, and zero secret leakage.
  - Passed all 51 frontend tests (182ms), 0 linter errors/warnings in oxlint, and 0 errors in TypeScript/Vite production build (`tsc -b && vite build` in 173ms).
  - Passed all 62 backend regression tests in 3.54s.

### Increment 5A: Real Verification API Client & Liveness Challenge Integration (Completed)
- **Typed Biometric Client Methods:**
  - Implemented `createChallenge(payload?: ChallengeRequest)` in `frontend/src/lib/apiClient.ts` to request cryptographic spoken liveness challenges from `POST /challenge`.
  - Implemented `verify(payload: VerifyRequest | FormData)` and alias `verifyAudio()` in `frontend/src/lib/apiClient.ts` to submit audio waveforms and challenge tokens to `POST /verify`.
  - Defined strict TypeScript interfaces in `frontend/src/types/index.ts` matching backend Pydantic models: `ChallengeRequest`, `ChallengeApiResponse`, `VerifyRequest`, and `VerifyApiResponse`.
- **Multipart Boundary Preservation & Header Hygiene:**
  - Enhanced `buildHeaders()` with `isFormData` detection. When sending `FormData`, manual `Content-Type: application/json` is omitted/stripped, ensuring the browser/fetch runtime automatically injects the required `multipart/form-data; boundary=...` header.
  - Enhanced `request()` and `post()` to pass `FormData` directly without stringifying to JSON.
  - Enhanced non-2xx error handling to extract FastAPI 422 validation error arrays and 400/401/403 details safely.
- **Zero-Fabrication Fail-Closed Security Invariant:**
  - Guaranteed that error responses (400, 401, 403, 404, 422, 500, network errors) strictly return `ok: false` and `data: null`, never manufacturing successful `accepted: true` or `UNLOCK` verdicts.
- **Automated Test Coverage:**
  - Added 10 automated unit and integration tests in `frontend/src/lib/apiClient.test.ts` validating `/challenge` and `/verify` endpoints, Bearer token attachment, multipart boundary handling, schema parsing, and all HTTP error pathways.
  - All 65 frontend tests pass cleanly (172ms), 0 lint errors in oxlint, and clean Vite production build.

### Increment 5B: Browser Audio Recording Hook & Lifecycle Management (Completed)
- **Reusable Audio Recorder Hook (`useAudioRecorder`) & Controller (`AudioRecorderController`):**
  - Implemented `useAudioRecorder` React hook and standalone `AudioRecorderController` class in `frontend/src/hooks/useAudioRecorder.ts`.
  - Captures genuine browser microphone audio via `navigator.mediaDevices.getUserMedia()` and `MediaRecorder`.
  - Strictly requests microphone permissions on explicit user invocation (`startRecording()`); never accesses audio hardware on mount or hook instantiation.
- **Dynamic Runtime MIME Negotiation & Extension Mapping:**
  - Evaluates candidates via `MediaRecorder.isTypeSupported()` in priority sequence: `audio/webm;codecs=opus`, `audio/webm`, `audio/ogg;codecs=opus`, `audio/ogg`, `audio/mp4`, `audio/aac`, `audio/wav`.
  - Preserves container integrity with `getMimeExtension(mimeType)` (`.webm`, `.ogg`, `.m4a`, `.aac`, `.wav`), strictly avoiding misrepresenting WebM/Opus byte payloads as WAV.
- **Robust Lifecycle, State & Error Handling:**
  - Tracks states: `idle` -> `requesting` -> `recording` -> `stopped` / `error`.
  - Provides elapsed duration tracking (100ms interval timer) and enforces a configurable maximum recording duration ceiling (default 10s) with automated stop.
  - Fail-closed error handling: rejects 0-byte recordings (`chunks.length === 0 || totalBytes === 0`), unsupported browser APIs, and internal recorder errors (`recorder.onerror`).
  - Translates browser errors into actionable user-facing messages: `NotAllowedError` (permission denied), `NotFoundError` (no microphone connected), `NotReadableError` (hardware in use).
- **Resource Hygiene & Track Cleanup:**
  - Guaranteed stopping of all `MediaStreamTrack` audio tracks when recording stops normally, is cancelled, encounters an error, or when the component unmounts.
  - Concurrency guards prevent duplicate start attempts, race conditions, or leaking streams during active or pending sessions.
- **Privacy & Security Boundaries:**
  - Zero persistence: recordings are never saved to disk, `localStorage`, or `IndexedDB`.
  - Zero leakage: raw audio bytes and biometric waveforms are never logged to console or sent over the network.
  - Strict scope boundary: `VerificationPage.tsx` was not modified and no network audio uploads were performed.
- **Automated Test Coverage:**
  - Added 19 comprehensive unit and lifecycle tests in `frontend/src/hooks/useAudioRecorder.test.ts` mocking `MediaStream`, `MediaStreamTrack`, `MediaRecorder`, and timers.
  - Tests verify: permission prompt on user action only, valid non-empty blob generation with accurate MIME types/extensions, browser MIME resolution, state transitions, permission denials, missing hardware, unsupported APIs, unsupported MIME formats, 0-byte fail-closed rejection, internal recorder errors, max duration auto-stop, track stopping on stop/cancel/destroy, concurrency safety, and zero localStorage/IndexedDB access.
  - Full frontend suite: 84/84 tests pass cleanly in ~390ms with 0 linter warnings and clean Vite build.

### Increment 5C: Real Backend-Driven Voice Verification UI & WebM Audio Decoding (Completed)
- **Real Backend-Driven UI Architecture (`VerificationPage.tsx`):**
  - Completely replaced the prototype verification simulator with live API-driven authentication.
  - Purged all mock data imports (`MOCK_SPEAKERS`, `MOCK_DEVICES` from `mockData.ts`), fake simulation state machines (`'genuine' | 'impostor' | 'spoof'`), simulated waveform bars, and client-side `Math.random()` digit generation.
  - Integrates `POST /challenge` via `apiClient.createChallenge()`, generating an unpredictable 3-digit CSPRNG sequence bound to a unique `session_id` with 60s Time-to-Live.
  - Live TTL countdown timer automatically marks the challenge as expired and burned when time elapses, preventing submissions of stale or invalid tokens.
- **Genuine Browser Microphone Recording Integration:**
  - Integrates the reusable `useAudioRecorder` hook; audio hardware access is requested strictly upon explicit user interaction ("Start Microphone Recording").
  - Provides audio playback preview via scoped `URL.createObjectURL` (cleanly revoked on unmount), audio metadata indicators (extension, container MIME type, duration, size in KB), and a "Discard & Re-Record" workflow.
  - Submits genuine audio payloads as `multipart/form-data` via `apiClient.verify()` with automatic boundary generation, binding `claimed_identity`, `challenge_id`, and `session_id`.
  - Single-attempt invalidation: burns the local challenge immediately upon submission, preventing accidental duplicate or replay attempts.
- **Backend WebM/Opus Decoding Support:**
  - Expanded `ALLOWED_EXTENSIONS` in `app/core/config.py` and `SUPPORTED_AUDIO_EXTENSIONS` in `audio_utils.py` to include `.webm`.
  - Proved that FFmpeg's native Matroska/WebM demuxer and `libopus` decoder convert browser WebM/Opus recordings cleanly to 16kHz mono PCM16 WAV in `audio_utils.load_audio()` and `liveness.transcribe_audio()`.
  - Added automated backend regression test `test_webm_audio_extension_accepted` in `tests/test_api.py`.
- **Identity Authorization & Fail-Closed Behavior:**
  - Preserved server-side role and mapping boundaries: ordinary authenticated users have no arbitrary speaker dropdown and are resolved strictly via `UserSpeakerMapping` in the database.
  - If an ordinary user has no mapping in `UserSpeakerMapping` (confirmed 0 mappings in database), the backend returns HTTP 403, and the UI transitions to a dedicated, prominent **Unmapped Voice Identity** fail-closed alert state detailing the required administrator setup.
  - Administrators are authorized to challenge and verify registered speaker profiles loaded live from `GET /speakers`.
- **Zero-Fabrication & Automated Test Suite:**
  - Renders verdicts, similarities, and liveness states strictly from the live backend response. Any error (400, 401, 403, 422, 500, network disconnect) fails closed with clear denial banners and never displays an UNLOCK verdict.
  - Added 12 comprehensive unit and integration tests in `frontend/src/components/pages/VerificationPage.test.ts` covering challenge display, real recording upload, genuine unlock, liveness denial, impostor denial, unmapped user 403, expired challenges, empty audio, HTTP errors, network failures, and zero-mock AST invariants.
  - All 96 frontend tests and 304 backend tests pass with 0 linter warnings and clean production build.

### Increment 7B: Firebase Production Build Configuration & Bundle Integrity Assertion (Completed)
- **Root Cause Resolution for Deployed Auth Failures:**
  - Diagnosed Increment 7A production failure where `apiKey: ""` was compiled into the deployed bundle due to multiline shell parsing issues, disabling Firebase SDK and causing synthetic mock token transmission that the backend rejected with HTTP 401.
  - Implemented robust, native environment loading using Vite's built-in `loadEnv` reading from `.env.production.local` and `.env.local` without multiline shell scraping.
- **Fail-Fast Build Validation:**
  - Added pre-flight configuration validation in `frontend/vite.config.ts`: production builds fail fast with descriptive errors if `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_PROJECT_ID`, `VITE_FIREBASE_AUTH_DOMAIN`, or `VITE_API_BASE_URL` are missing, empty, or placeholder strings.
  - Added `firebaseBundleValidatorPlugin` in `frontend/vite.config.ts` hooking into `generateBundle`: scans emitted JavaScript chunks and fails the build if any bundle contains an empty `apiKey: ""` or placeholder keys.
- **Bundle Security Assertions & Regression Testing:**
  - Created typed assertion helper `validateBundleContent` in `frontend/src/lib/bundleValidator.ts` detecting empty API keys, placeholder configurations, and server secret leaks (`private_key_id`, service-account credentials).
  - Added 7 automated unit and regression tests in `frontend/src/context/authUtils.test.ts` verifying empty API key rejection, template literal/quote variations, secret leak detection, and live validation of generated `dist/assets/index-*.js` files on disk.
### Increment 2A: Administrator User-to-Speaker Identity Mapping API (Completed)
- **Data Schemas & Minimization (`app/schemas/mapping.py`, `app/schemas/__init__.py`):**
  - Created `CreateMappingRequest`, `UserSpeakerMappingItem`, `MappingsListResponse`, `UnmappedSpeakerItem`, `UnmappedSpeakersResponse`, and `MappingOperationResponse`.
  - Enforced strict data minimization: biometric embeddings, private credentials, and secret verifiers are strictly excluded from all request and response schemas.
- **Admin-Only API Endpoints (`app/api/routes_admin_mappings.py`):**
  - `GET /admin/mappings`: Lists all active user-speaker mappings with enriched speaker metadata (`full_name`, `status`, `sample_count`).
  - `GET /admin/mappings/unmapped-speakers`: Lists unmapped enrolled speakers in `active` status eligible for account binding.
  - `POST /admin/mappings`: Links a Firebase UID to an active speaker identity. Enforces 1-to-1 cardinality with HTTP 409 Conflict rejection for duplicate assignments and HTTP 400/404 for inactive/missing speakers.
  - `DELETE /admin/mappings/{mapping_id}`: Unlinks a mapping record with guaranteed preservation of the underlying speaker record, biometric embedding, and enrollment audio.
- **Audit Logging & Transaction Safety:**
  - Guaranteed atomic transactions: successful link and unlink operations record an administrative security event (`event_type="admin_action"`, `status="logged"`, `severity="low"`) in the `security_events` table within the same transaction. If audit event logging fails, the mapping change rolls back completely.
  - Refactored `UserSpeakerRepository.create` to flush within a nested savepoint (`begin_nested()`), preventing `IntegrityError` handling from aborting caller-owned outer transactions.
- **Repository Extensions (`user_speaker_repository.py`, `speaker_repository.py`):**
  - Added `UserSpeakerRepository.get_by_id`, `delete_by_id`, and eager loading (`joinedload`) in `list_mappings` to prevent N+1 queries.
  - Added `SpeakerRepository.get_unmapped_active_speakers`.
- **Targeted Test Coverage (`tests/test_admin_mappings_api.py`):**
  - Added 16 comprehensive unit and integration tests covering happy paths, 401/403 authorization guards, 409 duplicate conflicts, 404 missing speakers/mappings, 400 inactive speakers, embedding preservation on unlink, atomic audit rollback, and response data minimization.
### Increment 2B: Administrator Identity Management UI (Completed)
- **API Client Extensions (`frontend/src/lib/apiClient.ts`):**
  - Added typed methods `getAdminMappings`, `getUnmappedSpeakers`, `createAdminMapping`, and `deleteAdminMapping`.
  - Added generic `delete<T>` method to `ApiClient` using existing Bearer token acquisition mechanism.
  - Strictly preserves data safety: zero client-supplied role flags, zero `isAdmin` parameters, and zero token leakage.
- **Frontend Identity Management Panel (`frontend/src/components/pages/IdentityManagementPage.tsx`):**
  - Built comprehensive administrative panel with live mappings table, search/filter bar, and count badges.
  - Implemented "Link Account" modal with Firebase UID input, eligible unmapped active speaker dropdown, optional administrative notes, and validation.
  - Implemented explicit "Unlink" confirmation modal with clear data safety notice guaranteeing that underlying speaker profiles, 192-d ECAPA-TDNN embeddings, and training audio are never deleted or modified.
  - Handled loading, empty, success, and error states (HTTP 409 duplicate conflicts, HTTP 403 forbidden, HTTP 401 expired sessions, and network failures).
- **Navigation & Role Guard (`App.tsx`, `Sidebar.tsx`, `Header.tsx`, `Layout.tsx`, `types/index.ts`):**
  - Added `'identities'` tab to `NavigationTab` type and Header titles.
  - Added "Identity Mappings" nav item to `Sidebar.tsx` rendered conditionally for authenticated administrators only.
  - Enforced presentation role check in `IdentityManagementPage.tsx` displaying an access-restricted state to non-admin operators while deferring authoritative authorization to backend RBAC.
  - Wired live mappings count telemetry in `App.tsx` for admin operators.
- **Targeted Test Coverage (`frontend/src/lib/identityMapping.test.ts`):**
  - Added 16 automated tests covering API client methods, 401/403/404/409 error handling, empty states, admin role guards, biometric data safety guarantees, and schema data minimization.
  - Full frontend suite expanded from 103 to 119 passing tests.

---

## 3. Verified Test Results
| Test Target | Command Executed | Exit Code | Result Summary |
| :--- | :--- | :--- | :--- |
| **Frontend Unit & Integration Suite** | `npm test` (in `frontend/`) | 0 | **119/119 tests PASSED in 490ms** (16 Identity Management UI tests + Bundle security & empty apiKey prevention, inlined client config validation, VerificationPage real UI flow, unmapped identity 403 fail-closed, audio recording upload, genuine unlock, liveness denial, impostor denial, expired challenge, zero-mock invariant, audio recorder lifecycle, track cleanup, MIME negotiation, duration limits, 0-byte rejection, challenge generation, multipart verification, boundary preservation, Bearer headers, Google sign-in role resolution, popup error translation, session persistence, token acquisition, security invariant, Firebase config inlining, demo-mode detection, metrics, search filtering) |
| **Frontend Code Quality** | `npm run lint` (in `frontend/`) | 0 | **0 warnings, 0 errors** across 34 files |
| **Frontend Production Build** | `npm run build` (in `frontend/`) | 0 | **Build passed in 106ms** (`dist/index.html`, `dist/assets/index-*.css`, `dist/assets/index-*.js` with verified non-empty Firebase client config) |
| **Full Backend Test Suite** | `.venv/bin/pytest -v` | 0 | **330/330 tests PASSED in 16.58s** (16 Admin Mappings API + 8 Liveness Unit + 36 API + 22 Auth + 7 Policy + 30 Device Auth + 12 DB Device Auth + 27 Database + 12 Device Repo + 8 Devices API + 21 Speaker Repo + 11 User Speaker Repo + 9 Persistent Auth + 17 Embeddings + 17 Seeder + 18 DB Speaker Service + 13 Event Repo + 15 Route Audit + 14 Metrics API + 4 Containerization + 6 Neon Database + WebM upload support) |
| **Admin Mappings API Suite** | `.venv/bin/pytest tests/test_admin_mappings_api.py -v` | 0 | **16/16 tests PASSED in 1.20s** (List mappings, unmapped speakers, link success, audit trail, 401/403 guards, 409 duplicate UID/speaker conflicts, 400 inactive speaker, 404 missing speaker/mapping, embedding preservation on unlink, atomic audit rollback, data minimization) |
| **Neon Database Suite** | `.venv/bin/pytest tests/test_neon_database.py -v` | 0 | **6/6 tests PASSED in 8.77s** (Live TLS PostgreSQL connection, dialect normalization, password masking, unpooled migration prioritization, 7 migrations chain, live repository queries) |
| **Metrics API Suite** | `.venv/bin/pytest tests/test_metrics_api.py -v` | 0 | **14/14 tests PASSED in 1.07s** (Admin access, 401/403 safety, device rejection, empty DB zeros, mixed outcomes & denominator, zero biometric div-zero guard, time window [start, end), invalid window 400, flow filter, invalid flow 400, data minimization, sanitized 500) |
| **Verification Route Audit Suite** | `.venv/bin/pytest tests/test_verification_route_audit.py -v` | 0 | **15/15 tests PASSED in 2.79s** (Verified event, rejection event, challenge_failed, device flow, decoding error, inference error, ffmpeg error, 401/403 no-log, pre-attempt no-log, fail-closed 500, correlation sanitization, data hygiene, replay protection) |
| **Verification Event Repository Suite** | `.venv/bin/pytest tests/test_verification_event_repository.py -v` | 0 | **13/13 tests PASSED in 0.85s** (Creation, caller rollback, retrieval, pagination, ordering, filters, [start, end) time window, count_events, count_by_outcome, input validations) |
| **Containerization Suite** | `.venv/bin/pytest tests/test_containerization.py -v` | 0 | **4/4 tests PASSED in 0.42s** (Production dependencies, Dockerfile non-root & ffmpeg & healthcheck, .dockerignore exclusions, warmup script) |
| **Database & Migration Suite** | `.venv/bin/pytest tests/test_database.py -v` | 0 | **27/27 tests PASSED in 1.63s** (VerificationEvent and SecurityEvent models, bounded taxonomy validators, metadata privacy checks, migration ea5fe481812c upgrade/downgrade, composite indexes, ON DELETE SET NULL retention) |
| **Devices API Suite** | `.venv/bin/pytest tests/test_devices_api.py -v` | 0 | **8/8 tests PASSED in 0.67s** (Admin RBAC, data minimization secret exclusion, status counts, 401/403 safety, DB error handling) |
| **Speaker Service Suite** | `.venv/bin/pytest tests/test_database_speaker_service.py -v` | 0 | **18/18 tests PASSED in 2.14s** (1-to-N identify, 1-to-1 verify, score ranking, inactive/missing/corrupt embeddings, empty registry, DB failures fail-closed, ordinary user ownership, device authorization, challenge burn ordering, session isolation) |
| **Speaker Seeder Suite** | `.venv/bin/pytest tests/test_seed_speakers.py -v` | 0 | **17/17 tests PASSED in 1.15s** (Synthetic seeding, sample count metadata, excluded keys, validation, dry-run, idempotency, conflict aborts, rollback) |
| **Embedding Validation Suite** | `.venv/bin/pytest tests/test_embeddings.py -v` | 0 | **17/17 tests PASSED in 1.09s** (Roundtrip, float32 precision, cosine similarity >= 0.999999, NaN/Inf rejection, non-numeric rejection, privacy guarantees) |
| **Speaker Repository Suite** | `.venv/bin/pytest tests/test_speaker_repository.py -v` | 0 | **20/20 tests PASSED in 0.82s** (Embedding persistence, get_embedding, set_embedding, invalid dimension rejection, rollback) |
| **Live Neon PostgreSQL Connectivity** | Direct SQLAlchemy 2.0 + psycopg 3 TLS query | 0 | Connected to `neondb` on PostgreSQL 18.6 in `aws-us-east-2`, verified all 7 tables, queried repositories |
| **Live Uvicorn Server Smoke Test** | `uvicorn app.main:app` + HTTP probe `GET /` | 0 | HTTP 200 OK, `status: "online"`, `version: "1.0.0"` |
| **Model Inference** | `.venv/bin/python predict.py "processed_dataset/Zubair/Zubair_Enrollment_R01.wav"` | 0 | Identifies `Zubair` (Score: 0.8668, Margin: +0.6073) |
| **Evaluation Suite** | `.venv/bin/python evaluate.py` | 0 | 27/27 test samples correct (100% accuracy, Macro F1: 1.0) |
| **Threshold Calibration** | `.venv/bin/python tune_threshold.py` | 0 | Generates ROC/DET curves; Genuine Mean: 0.8136, Impostor: 0.2520 |
| **Streamlit Smoke Test** | `streamlit.testing.v1.AppTest.from_file('app.py')` | 0 | AppTest initializes, runs with zero exceptions across 4 tabs |

---

## 4. Known Issues & Remaining Security Risks
1. **Security Event Logging Uninstrumented (Current Limitation):**
   - *Status:* `SecurityEvent` schema and Alembic migration are established. However, security event repository, API routes, route instrumentation (e.g. rate limit exhaustion, unauthorized access attempts, tampering), and frontend integration remain to be implemented.
2. **Frontend Development Demonstration Mode:**
   - *Status:* When `frontend/.env.local` is not populated with real Firebase Web credentials, client operates in local demonstration mode with preset operator accounts. Real Firebase ID tokens require provisioning in the Firebase Console.
3. **In-Memory Store & Rate Limiter Single-Process Boundary (`SEC-006`):**
   - *Risk:* `InMemoryChallengeStore`, `InMemoryNonceStore`, and `InMemoryRateLimiter` are process-local. Running Uvicorn with `--workers > 1` causes state divergence.
   - *Plan:* Replace with persistent storage (PostgreSQL/Redis) in Milestone 3C.4 (Shared Challenge & Rate Limit Storage).
4. **Pre-Shared Device Key Replay Limitation (`SEC-001` partial):**
   - *Status:* Constrained microcontrollers using Scheme B (`X-Device-Key`) lack application-layer replay resistance. Scheme A (HMAC-SHA256 with nonce and timestamp) is implemented and recommended for production terminals.
5. **Small Evaluation Dataset & Threshold Discordance (`SEC-009`):**
   - *Risk:* 0.00% EER is computed on only 3 speakers (27 test samples). Max impostor score of 0.6802 exceeds baseline threshold of 0.25.
   - *Plan:* Retain 0.25 for prototype compatibility; conduct comprehensive multi-session biometric evaluation before production.
6. **Voice Cloning Limitations (`SEC-010`):**
   - *Risk:* Spoken digit challenge-response mitigates static replay attacks, but does not defeat low-latency real-time generative voice cloning.

---

## 5. Next Recommended Step
Proceed to **Increment 4C: Cloud CI/CD Automation (GitHub Actions to GHCR & Azure Deployment)**:
1. Create `.github/workflows/deploy.yml` to automatically build, test, and push the backend container image to GitHub Container Registry (`ghcr.io`).
2. Configure Azure Container Apps secret references for `DATABASE_URL` and Firebase credentials.
3. Configure Azure Static Web Apps deployment for the React frontend.







