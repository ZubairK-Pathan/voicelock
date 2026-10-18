# Project Status — VoiceLock Enterprise

**Last Updated:** October 18, 2026  
**Current Milestone:** Increment 1B — Safe Speaker Database Seeder (Completed)  
**Current Git State:** Branch `feature/enterprise-foundation`  
**Application Run Status:** Fully Operational (Safe speaker database seeder active, 208 backend automated tests passing in 3.33s, 6 frontend unit tests passing, Streamlit AppTest, ML inference, and calibration passing)

---

## 1. Executive Status
Increment 1B implements the safe, repeatable speaker database seeder (`scripts/seed_speakers.py`) for importing the ten approved real speaker biometric profiles from `speaker_profiles/profiles.pkl` into the persistent database using `SpeakerRecord` and `SpeakerRepository`. Strict pre-write validation guarantees that every loaded vector is 192-dimensional, numeric, and finite (rejecting NaN, Inf, and non-numeric inputs), with non-approved identities (`abc`, `maam`) filtered out by default. Idempotency and conflict handling ensure that identical existing records are safely skipped, while conflicting existing records (different embeddings, inactive statuses, or dimension mismatches) abort the entire transaction to protect biometric data integrity. The script enforces atomic session commit/rollback, masks credentials, suppresses vector values, and supports `--dry-run` inspection. The automated test suite expanded from 191 to 208 tests (17 dedicated seeder tests in `tests/test_seed_speakers.py`), verifying end-to-end seeding, idempotency, conflict aborts, midway failure rollbacks, and CLI behavior with zero ML or UI regressions.


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
  - Full automated backend test suite expanded from 191 to **208 tests passing in 3.33s**.

---

## 3. Verified Test Results
| Test Target | Command Executed | Exit Code | Result Summary |
| :--- | :--- | :--- | :--- |
| **Speaker Seeder Suite** | `.venv/bin/pytest tests/test_seed_speakers.py -v` | 0 | **17/17 tests PASSED in 1.15s** (Synthetic seeding, sample count metadata, excluded keys, validation, dry-run, idempotency, conflict aborts, rollback) |
| **Embedding Validation Suite** | `.venv/bin/pytest tests/test_embeddings.py -v` | 0 | **17/17 tests PASSED in 1.09s** (Roundtrip, float32 precision, cosine similarity >= 0.999999, NaN/Inf rejection, non-numeric rejection, privacy guarantees) |
| **Speaker Repository Suite** | `.venv/bin/pytest tests/test_speaker_repository.py -v` | 0 | **20/20 tests PASSED in 0.82s** (Embedding persistence, get_embedding, set_embedding, invalid dimension rejection, rollback) |
| **Database Migration Suite** | `.venv/bin/pytest tests/test_database.py -v` | 0 | **17/17 tests PASSED in 1.01s** (Migration 8046c184216a upgrade/downgrade, embedding_json column inspection, ORM persistence) |
| **Full Automated Test Suite** | `.venv/bin/pytest -v` | 0 | **208/208 tests PASSED in 3.33s** (35 API + 22 Auth + 7 Policy + 30 Device Auth + 12 DB Device Auth + 17 Database + 12 Device Repo + 20 Speaker Repo + 10 User Speaker Repo + 9 Persistent Auth + 17 Embeddings + 17 Seeder) |
| **Frontend Unit Tests** | `npm test` (in `frontend/`) | 0 | **6/6 tests PASSED in 22ms** (Bearer token attachment, unauthenticated routes, error suppression, 401/403 safety, JSON parsing) |
| **Frontend Code Quality** | `npm run lint` (in `frontend/`) | 0 | **0 warnings, 0 errors** across 24 files |
| **Frontend Production Build** | `npm run build` (in `frontend/`) | 0 | **Build passed in 153ms** |
| **Model Inference** | `.venv/bin/python predict.py "processed_dataset/Zubair/Zubair_Enrollment_R01.wav"` | 0 | Identifies `Zubair` (Score: 0.8668, Margin: +0.6073) |
| **Evaluation Suite** | `.venv/bin/python evaluate.py` | 0 | 27/27 test samples correct (100% accuracy, Macro F1: 1.0) |
| **Threshold Calibration** | `.venv/bin/python tune_threshold.py` | 0 | Generates ROC/DET curves; Genuine Mean: 0.8136, Impostor: 0.2520 |
| **Streamlit Smoke Test** | `streamlit.testing.v1.AppTest.from_file('app.py')` | 0 | AppTest initializes, runs with zero exceptions across 4 tabs |


---

## 4. Known Issues & Remaining Security Risks
1. **Frontend Development Demonstration Mode:**
   - *Status:* When `frontend/.env.local` is not populated with real Firebase Web credentials, client operates in local demonstration mode with preset operator accounts. Real Firebase ID tokens require provisioning in the Firebase Console.
2. **In-Memory Store & Rate Limiter Single-Process Boundary (`SEC-006`):**
   - *Risk:* `InMemoryChallengeStore`, `InMemoryNonceStore`, and `InMemoryRateLimiter` are process-local. Running Uvicorn with `--workers > 1` causes state divergence.
   - *Plan:* Replace with persistent storage (PostgreSQL/Redis) in Milestone 3C.4 (Shared Challenge & Rate Limit Storage).
3. **Pre-Shared Device Key Replay Limitation (`SEC-001` partial):**
   - *Status:* Constrained microcontrollers using Scheme B (`X-Device-Key`) lack application-layer replay resistance. Scheme A (HMAC-SHA256 with nonce and timestamp) is implemented and recommended for production terminals.
4. **Small Evaluation Dataset & Threshold Discordance (`SEC-009`):**
   - *Risk:* 0.00% EER is computed on only 3 speakers (27 test samples). Max impostor score of 0.6802 exceeds baseline threshold of 0.25.
   - *Plan:* Retain 0.25 for prototype compatibility; conduct comprehensive multi-session biometric evaluation before production.
5. **Voice Cloning Limitations (`SEC-010`):**
   - *Risk:* Spoken digit challenge-response mitigates static replay attacks, but does not defeat low-latency real-time generative voice cloning.

---

## 5. Next Recommended Step
Proceed to **Milestone 4C: Live Dashboard & Real Backend API Integration**:
1. Connect `OverviewPage`, `SpeakersPage`, and `DevicesPage` to the FastAPI backend endpoints via `apiClient`.
2. Connect `GET /speakers` to populate the speakers table with persistent database records.
3. Wire `POST /challenge` and `POST /verify` to execute real biometric inference and Vosk liveness detection with browser audio uploads.
4. Replace mock data with live operational state while maintaining graceful fallback and error boundaries.





