# Architecture Specification — VoiceLock Enterprise

## 1. System Overview
VoiceLock Enterprise is a biometric access-control system that pairs speaker recognition (ECAPA-TDNN) and anti-spoofing challenge-response liveness detection with a full-stack web dashboard and an ESP32 desk demonstration terminal.

---

## 2. Current Reference Architecture

```
┌────────────────────────────────────────────────────────┐
│               Streamlit Web Application                │
│                         (app.py)                       │
└───────────────────────────┬────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
┌─────────────────────────┐   ┌───────────────────────────┐
│     Inference Engine    │   │      Liveness Engine      │
│       (predict.py)      │   │       (liveness.py)       │
├─────────────────────────┤   ├───────────────────────────┤
│ SpeechBrain ECAPA-TDNN  │   │ BaseChallengeStore (ABC)  │
│ 192-dim Voiceprint      │   │ InMemoryChallengeStore    │
│ Cosine Similarity       │   │ CSPRNG (secrets.randbelow)│
│ Server Threshold = 0.25 │   │ Offline Vosk STT Model    │
└───────────┬─────────────┘   │ Single-Attempt Burn-on-Use│
            │                 └─────────────┬─────────────┘
            │                               │
            └───────────────┬───────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│             Audio Preprocessing & Storage              │
│                    (audio_utils.py)                    │
├────────────────────────────────────────────────────────┤
│ - FFmpeg 16kHz Mono PCM16 Normalization                │
│ - speaker_profiles/profiles.pkl (Pickle Dict)          │
│ - dataset/ & processed_dataset/ (Audio Files)          │
└────────────────────────────────────────────────────────┘
```

### Challenge Lifecycle and In-Memory Storage Model
- **Interface:** `BaseChallengeStore` (abstract base class defining `create_challenge`, `get_challenge`, `validate_and_consume`, `cleanup_expired`).
- **Development Implementation:** `InMemoryChallengeStore` using `threading.Lock` and injectable `time_func` clock abstraction for deterministic testability.
- **Production Boundary:** Designed for single-worker processes; horizontally scaled or multi-worker deployments must substitute a shared distributed implementation (e.g. Redis or PostgreSQL).
- **Invalidation Policy:** Single-Attempt Invalidation ("burn-on-use") — challenges transition atomically from `PENDING` to `CONSUMED` on first submission attempt to prevent concurrent replay. Early rejection occurs before audio upload spooling to prevent disk and buffering denial-of-service.

---

## 3. Modular Backend Package Architecture (`app/`)

As of Milestone 2C, the backend has been modularized into a decoupled package layout while preserving `cloud_api.py` as a 100% backward-compatible root entry point:

```
Voice Recognition/
├── app.py                     # Streamlit reference application (unchanged)
├── cloud_api.py               # Backward-compatible entry point re-exporting app & services
├── liveness.py                # Vosk STT engine and BaseChallengeStore abstractions
├── predict.py                 # SpeechBrain ECAPA-TDNN biometric inference
├── audio_utils.py             # Audio normalization and voiceprint serialization
├── app/                       # Modular FastAPI application package
│   ├── __init__.py            # Exports `app` and `create_app`
│   ├── main.py                # Application factory, lifespan, CORS, and size limiter middleware
│   ├── core/
│   │   ├── config.py          # Centralized configuration (thresholds, origins, device registry)
│   │   ├── errors.py          # HTTP exception helpers
│   │   ├── auth_policy.py     # Declarative RBAC permissions and endpoint matrix
│   │   ├── auth.py            # Firebase ID-token verification and role resolution
│   │   ├── device_auth.py     # IoT HMAC-SHA256 signature scheme, nonce store, and actor resolution
│   │   ├── middleware.py      # ASGI request-body streaming size limiter (terminates oversized payloads)
│   │   └── rate_limit.py      # In-memory sliding-window limiter & inference concurrency semaphore
│   ├── schemas/
│   │   ├── challenge.py       # Pydantic models for challenge request/response
│   │   ├── mapping.py         # Pydantic models for admin identity mappings
│   │   ├── security_event.py  # Pydantic models & safe allowlist for security audit events
│   │   └── verification.py    # Pydantic models for identify, verify, speakers, and health
│   ├── repositories/
│   │   ├── speaker_repository.py # Speaker profile CRUD and activation
│   │   ├── user_speaker_repository.py # 1-to-1 account-to-voiceprint mappings
│   │   ├── device_repository.py  # Terminal hardware registration & secrets
│   │   ├── verification_event_repository.py # Biometric verification outcomes
│   │   └── security_event_repository.py     # Paginated audit log queries & filters
│   ├── services/
│   │   ├── speaker_service.py # Singleton management for ECAPA-TDNN model and profiles
│   │   ├── challenge_service.py # Challenge store singleton and helper wrappers
│   │   └── verification_service.py # Upload streaming with Content-Length check & cleanup
│   └── api/
│       ├── __init__.py        # Aggregate api_router
│       ├── routes_health.py   # GET /
│       ├── routes_speakers.py # GET /speakers
│       ├── routes_devices.py  # GET /devices, POST /devices, DELETE /devices
│       ├── routes_challenges.py # POST /challenge
│       ├── routes_verification.py # POST /identify, POST /verify, WS /ws/identify
│       ├── routes_metrics.py  # GET /metrics, GET /metrics/verification
│       ├── routes_admin_mappings.py # GET/POST/DELETE /admin/mappings
│       └── routes_security_events.py # GET /admin/security-events
└── tests/
    ├── test_api.py            # Baseline API contract and upload security suite
    ├── test_auth.py           # Firebase authentication, RBAC, and WebSocket suite
    ├── test_admin_mappings_api.py # Admin identity mapping test suite
    ├── test_security_events_api.py # Paginated security audit events API suite
    └── test_database.py       # SQLAlchemy 2.0 and Alembic migration test suite
```

### Module Responsibilities & Lifecycle Guarantees
1. **Single Model Initialization:** `speaker_service.get_system()` caches the loaded ECAPA-TDNN model and profiles dictionary as process singletons, pre-warmed once at application startup via FastAPI `lifespan`.
2. **Dynamic Lookup Pattern for Test Compatibility:** Route handlers dynamically look up functions (`predict_speaker`, `verify_speaker`, `run_liveness_check`, `save_upload`, `get_system`, `default_challenge_store`) through `sys.modules.get("cloud_api")`. This cleanly allows existing and future tests using `unittest.mock.patch("cloud_api.*")` to mock behavior without circular import deadlocks.
3. **Decoupled Service Layer:** Business logic for upload handling and challenge management is isolated from routing logic, enabling seamless future migration of the challenge store to Redis or PostgreSQL without modifying HTTP endpoints.

---

## 4. Target Enterprise Architecture

```
                               ┌─────────────────────────┐
                               │   React + TS Frontend   │
                               │  (Vite + Design System) │
                               └────────────┬────────────┘
                                            │ Firebase ID Token (RS256 JWT)
                                            ▼
┌──────────────────────┐ HTTPS POST  ┌──────────────────────────────────────────────────┐
│ ESP32 Desk Terminal  │────────────►│               FastAPI Backend Server             │
│ (Microphone/Display) │ Device Key  │                                                  │
└──────────────────────┘ (HMAC-SHA)  ├──────────────────────────────────────────────────┤
                                     │ - API Routes (/auth, /verify, /enroll, /devices) │
                                     │ - Middleware: Rate Limits, Streaming Size Limits │
                                     │ - Auth Middleware (Firebase JWT & Device Keys)   │
                                     │ - Challenge Service (TTL, CSPRNG, Atomic Lock)   │
                                     │ - Biometric Inference Service (ECAPA-TDNN)       │
                                     └──────────────┬───────────────────┬───────────────┘
                                                    │                   │
                                                    ▼                   ▼
                                       ┌───────────────────────┐  ┌───────────────────┐
                                       │ PostgreSQL Database   │  │ Biometric Storage │
                                       │ (SQLAlchemy + Alembic)│  │ (Protected Files/ │
                                       │ - Users & Roles       │  │  Artifact Store)  │
                                       │ - Devices             │  │ - 192-d vectors   │
                                       │ - Challenge Records   │  │ - Encrypted voice │
                                       │ - Audit Logs          │  │   metadata        │
                                       └───────────────────────┘  └───────────────────┘
```

---

## 5. Identity Separation & Access Control Model

To eliminate privilege escalation, identity confusion, and spoofing vulnerabilities, VoiceLock strictly decouples three fundamental identity domains:

```
┌─────────────────────────────────┐      ┌─────────────────────────────────┐
│        Web User Identity        │      │       IoT Device Identity       │
│  - Firebase Auth UID (RS256)    │      │  - Physical Device ID           │
│  - Email & Role Claims          │      │  - Cryptographic Device Secret  │
│  - Subject of Admin/Dashboard   │      │  - Subject of Door Access Relays│
└────────────────┬────────────────┘      └────────────────┬────────────────┘
                 │                                        │
                 │ Maps to 1-to-N                         │ Interacts with
                 ▼                                        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                      Enrolled Speaker / Voice Identity                   │
│  - Passive Biometric Voiceprint (192-d ECAPA-TDNN embedding vector)      │
│  - speaker_id (Alphanumeric identifier, e.g., 'spk_zubair_01')           │
│  - Validated ONLY via Cosine Similarity >= 0.25 AND Spoken Liveness Pass │
└──────────────────────────────────────────────────────────────────────────┘
```

### Identity Definitions & Non-Negotiable Boundaries:
1. **Web User Identity (`IdentityType.WEB_USER`):**
   - **Authentication:** Verified via Firebase Admin SDK (`firebase_admin.auth.verify_id_token(token, check_revoked=True)`).
   - **Authority:** Authenticates a human operator or employee accessing the web console.
   - **Crucial Rule:** A Firebase `uid` does NOT automatically correspond to a speaker voice identity. A user may have an administrative web account without being enrolled as a voiceprint, or may be explicitly mapped to a speaker profile via a relational mapping in PostgreSQL (`users.speaker_profile_id`).
2. **Enrolled Speaker / Voice Identity (`IdentityType.SPEAKER_VOICE`):**
   - **Authentication:** Passive acoustic biometric credential evaluated strictly via cosine similarity against enrolled 192-dimensional embeddings.
   - **Authority:** Validates the physical presence and identity of a human speaker. Cannot initiate administrative actions or manage API configurations.
   - **Crucial Rule:** Stating `claimed_identity: "Zubair"` is an unverified assertion until both spoken digit liveness check AND cosine similarity verification succeed.
3. **IoT Device Identity (`IdentityType.IOT_DEVICE`):**
   - **Authentication:** Cryptographic Pre-Shared Key (PSK) or HMAC signature (`X-Device-Key` header verified against hashed device tokens stored in database).
   - **Authority:** Validates that the client requesting challenge issuance or verification is an authorized physical kiosk or door relay terminal.
   - **Crucial Rule:** Supplying a `device_id` without a cryptographically verifiable secret is strictly rejected. A device cannot list enrolled speakers or enroll new users.

---

## 6. Role-Based Access Control (RBAC) & Endpoint Matrix

| Endpoint | Method | Auth Scheme | Rate Limit | Stream Limit | Allowed Roles | Security Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `GET /` | GET | `Public` | Unbounded | 1 MB | `Anonymous`, `User`, `Device`, `Admin` | System health and load balancer discovery. Exposes only online status; hides thresholds and counts. |
| `GET /speakers` | GET | `FirebaseJWT` | Unbounded | 1 MB | `Admin` | Directory listing. Restricted to prevent employee enumeration and targeted biometric harvesting. |
| `POST /challenge` | POST | `Either` (JWT or Device) | 30 req/min | 1 MB | `Device`, `User`, `Admin` | Challenge digit generation. Ordinary users can only challenge their own voice identity; devices can challenge for door access. |
| `POST /verify` | POST | `Either` (JWT or Device) | 30 req/min | 10 MB + 64KB | `Device`, `User`, `Admin` | 1-to-1 door access verification. Concurrency-bounded (max 4). Ordinary users restricted to self-verification. |
| `POST /identify` | POST | `FirebaseJWT` | 15 req/min | 10 MB + 64KB | `Admin` | 1-to-N unconstrained speaker identification. Concurrency-bounded (max 4). Restricted to Admin due to biometric probing risk. |
| `WS /ws/identify` | WS | `FirebaseJWT` | 100 frames/sess | 10 MB frame | `Admin` | Real-time streaming identification. Restricted to Admin with upfront handshake, frame ceilings, and inference semaphore. |

---

## 7. Authentication Flow Architecture

### Web User Access Flow:
```
[User Browser] ──(1. Login)──► [Firebase Auth]
       │                              │
       │◄───(2. ID Token JWT)─────────┘
       │
       ▼ (3. HTTP Request with Authorization: Bearer <ID_TOKEN>)
[FastAPI Backend]
       ├── (4. Verify Signature via Firebase Admin SDK & Google JWKS)
       ├── (5. Extract UID; check server bootstrap ADMIN_EMAILS/ADMIN_UIDS)
       └── (6. Authorize Route via app/core/auth_policy.py & resolve_user_voice_identity)
```

### ESP32 Device Terminal Flow (Replay-Resistant HMAC-SHA256 Scheme):
```
[ESP32 Hardware Terminal]
       │
       ▼ (1. POST /challenge with X-Device-ID, X-Device-Timestamp, X-Device-Nonce, X-Device-Signature)
[FastAPI Backend]
       ├── (2. Validate timestamp within 300s window & verify nonce freshness via InMemoryNonceStore)
       ├── (3. Validate HMAC-SHA256 signature in constant time against device secret)
       ├── (4. Issue 3-digit CSPRNG challenge bound to device_id & session_id)
       └── (5. Return challenge digits & 60s TTL)
[ESP32 Hardware Terminal]
       ├── (6. Prompt user on OLED display: "Speak digits: 4 8 2")
       ├── (7. Record audio from I2S microphone)
       ▼ (8. POST /verify with audio, challenge_id, session_id, claimed_identity, & HMAC headers)
[FastAPI Backend]
       ├── (9. Validate HMAC signature, timestamp, and nonce)
       ├── (10. Enforce ASGI streaming byte ceiling prior to multipart disk spooling)
       ├── (11. Validate Device & atomically consume challenge BEFORE upload spooling)
       ├── (12. Run Vosk spoken digit liveness check; fail closed on mismatch)
       ├── (13. Acquire inference concurrency slot [1 of 4])
       ├── (14. Run SpeechBrain ECAPA-TDNN 1-to-1 verification against claimed_identity)
       └── (15. Release inference slot; return JSON decision: {"accepted": true, "action": "UNLOCK", ...})
[ESP32 Hardware Terminal]
       └── (16. Trigger physical door relay if action == "UNLOCK")
```

---

## 8. ASGI Request-Body Streaming Protection Architecture (`app/core/middleware.py`)

Starlette’s default `MultiPartParser` buffers incoming uploads in memory and spools excess chunks to disk *before* endpoint routing dependencies execute. To prevent resource exhaustion:
1. **Pre-check Inspection:** Fast check on `Content-Length`. If declared length exceeds route limit, connection returns HTTP 413 immediately.
2. **Raw Stream Limiter:** Wraps ASGI `receive` callable with `limited_receive`. Counts cumulative bytes on-the-fly and raises `PayloadTooLargeError` as soon as chunks cross the ceiling (10 MB + 64 KB for uploads, 1 MB for standard endpoints).
3. **Downstream Safety:** Body chunks pass through transparently to downstream Starlette multipart parsing without double-buffering or memory accumulation.

---

## 9. Rate Limiting & Resource Protection Architecture (`app/core/rate_limit.py`)

1. **Sliding-Window Limiter (`InMemoryRateLimiter`):** Tracks timestamp lists per identity key. Stale timestamps are purged periodically to maintain strictly bounded memory.
2. **Principal-Bound Keys:** Rate limit keys are derived exclusively from verified principal identities (`user:<uid>`, `device:<device_id>`). Caller-supplied spoofable headers (e.g. `X-Forwarded-For`) are never trusted for authenticated entities.
3. **Inference Concurrency Semaphore:** `asyncio.Semaphore(4)` ensures that at most 4 parallel ECAPA-TDNN feature extractions can execute concurrently across HTTP and WebSocket endpoints, preventing CPU core starvation and denial of service.
4. **Horizontal Scaling Boundary:** In-memory rate limiting and nonce stores are process-local. Distributed horizontal scaling across multiple instances requires shared Redis state (scheduled for Milestone 3C).

---

## 10. Database Architecture & Alembic Migrations (`app/db/`)

Milestone 3C.1 establishes the durable storage foundation utilizing SQLAlchemy 2.0 and Alembic:

### Architecture & Components
1. **Declarative Base (`app/db/base.py`):**
   - Standard SQLAlchemy 2.0 `DeclarativeBase` mapping typed attributes (`Mapped[T]`, `mapped_column()`).
   - Initial migration verification entity: `SchemaInitialization` (`schema_initializations` table).
2. **Session & Engine Lifecycle (`app/db/session.py`):**
   - **Lazy Initialization:** Engines and session factories are instantiated on first use, avoiding premature database connections during module import, CLI usage, or test execution.
   - **URL Normalization & Safe Masking:** Normalizes `postgres://` and `postgresql://` connection strings to `postgresql+psycopg://`. `mask_database_url()` redacts database passwords with `***` before logging.
   - **Production Fail-Closed:** Missing `DATABASE_URL` in production immediately raises `RuntimeError`.
   - **Connection Pooling:** PostgreSQL engines configure `QueuePool` with configurable `pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle` (1800s), and `pool_pre_ping=True` (active keepalive verification). In-memory SQLite uses `StaticPool`.
   - **Transaction Management:** Provides `get_db()` generator dependency for FastAPI request lifecycles and `@contextmanager get_db_context()` for CLI scripts and background workers.
3. **Alembic Migration Pipeline (`alembic/`):**
   - Configured via `alembic.ini` and `alembic/env.py`.
   - `env.py` dynamically resolves connection parameters via `get_database_url()` and connects to `Base.metadata`.
   - Initial migration `e32dc984b290_create_schema_initializations_table.py` validates upgrade and downgrade lifecycles against disposable databases.
   - Domain entity migrations (speaker profiles, user identity mappings, device registrations, challenges, audit logs) are structured as sequential increments across 3C.2 to 3C.5.


