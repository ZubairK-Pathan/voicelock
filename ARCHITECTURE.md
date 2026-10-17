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
│   ├── main.py                # Application factory and lifespan handler
│   ├── core/
│   │   ├── config.py          # Centralized configuration (SERVER_THRESHOLD, MAX_AUDIO_SIZE_BYTES)
│   │   └── errors.py          # HTTP exception helpers
│   ├── schemas/
│   │   ├── challenge.py       # Pydantic models for challenge request/response
│   │   └── verification.py    # Pydantic models for identify, verify, speakers, and health
│   ├── services/
│   │   ├── speaker_service.py # Singleton management for ECAPA-TDNN model and profiles
│   │   ├── challenge_service.py # Challenge store singleton and helper wrappers
│   │   └── verification_service.py # Upload streaming with Content-Length check & cleanup
│   └── api/
│       ├── __init__.py        # Aggregate api_router
│       ├── routes_health.py   # GET /
│       ├── routes_speakers.py # GET /speakers
│       ├── routes_challenges.py # POST /challenge
│       └── routes_verification.py # POST /identify, POST /verify, WS /ws/identify
└── tests/
    └── test_api.py            # Comprehensive 35-test automated test suite
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

| Endpoint | Method | Auth Scheme | Required Permissions | Allowed Roles | Security Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET /` | GET | `Public` | `health:read` | `Anonymous`, `User`, `Device`, `Admin` | System health and load balancer discovery. Exposes only online status; hides thresholds and counts. |
| `GET /speakers` | GET | `FirebaseJWT` | `speakers:list` | `Admin` | Directory listing. Restricted to prevent employee enumeration and targeted biometric harvesting. |
| `POST /challenge` | POST | `Either` (JWT or DeviceKey) | `challenge:create` | `Device`, `User`, `Admin` | Challenge digit generation. Requires authenticated caller to prevent in-memory store flooding. |
| `POST /verify` | POST | `Either` (JWT or DeviceKey) | `verify:biometric` | `Device`, `User`, `Admin` | 1-to-1 door access verification. Early invalidation enforces single-attempt consumption before audio I/O. |
| `POST /identify` | POST | `FirebaseJWT` | `identify:biometric` | `Admin` | 1-to-N unconstrained speaker identification. Restricted to Admin due to biometric probing risk. |
| `WS /ws/identify` | WS | `FirebaseJWT` | `identify:biometric` | `Admin` | Real-time streaming identification. Restricted to Admin with connection and frame limits. |

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
       ├── (5. Extract UID and Custom Role Claims: admin/user)
       └── (6. Authorize Route via app/core/auth_policy.py)
```

### ESP32 Device Terminal Flow:
```
[ESP32 Hardware Terminal]
       │
       ▼ (1. POST /challenge with X-Device-ID: dev_front_door_01, X-Device-Key: <TOKEN>)
[FastAPI Backend]
       ├── (2. Validate Device Key against hashed device registry)
       ├── (3. Issue 3-digit CSPRNG challenge bound to device_id & session_id)
       └── (4. Return challenge digits & 60s TTL)
[ESP32 Hardware Terminal]
       ├── (5. Prompt user: "Speak digits: 4 8 2")
       ├── (6. Record audio from I2S microphone)
       ▼ (7. POST /verify with audio, challenge_id, session_id, claimed_identity, X-Device-Key)
[FastAPI Backend]
       ├── (8. Validate Device Key & atomically consume challenge BEFORE upload spooling)
       ├── (9. Run Vosk spoken digit liveness check; fail closed on mismatch)
       ├── (10. Run SpeechBrain ECAPA-TDNN 1-to-1 verification against claimed_identity)
       └── (11. Return JSON decision: {"accepted": true, "action": "UNLOCK", ...})
[ESP32 Hardware Terminal]
       └── (12. Trigger physical door relay if action == "UNLOCK")
```

