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
                                            │ Firebase ID Token
                                            ▼
┌──────────────────────┐ HTTPS POST  ┌──────────────────────────────────────────────────┐
│ ESP32 Desk Terminal  │────────────►│               FastAPI Backend Server             │
│ (Microphone/Display) │ Device Key  │                                                  │
└──────────────────────┘             ├──────────────────────────────────────────────────┤
                                     │ - API Routes (/auth, /verify, /enroll, /devices) │
                                     │ - Middleware: Rate Limits, Max Uploads, Auth     │
                                     │ - Challenge-Response Service (TTL, CSPRNG)       │
                                     │ - Biometric Inference Service                    │
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

## 4. Identity Separation Model
To prevent privilege escalation and unauthorized access, four identities are strictly decoupled:
1. **Web User Identity:** Authenticated via Firebase Authentication (JWT verified on backend).
2. **Voice Identity:** Biometric profile embedding evaluated via cosine similarity by the ML engine.
3. **IoT Device Identity:** Physical demonstration device authenticated via signed pre-shared keys / HMAC tokens.
4. **Application Authorization:** Server-enforced Role-Based Access Control (RBAC) governing what operations each authenticated entity may perform.
