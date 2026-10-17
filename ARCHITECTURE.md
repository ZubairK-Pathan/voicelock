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
│ SpeechBrain ECAPA-TDNN  │   │ Offline Vosk STT Model    │
│ 192-dim Voiceprint      │   │ 3-digit challenge speech  │
│ Cosine Similarity       │   │ Word-to-digit parsing     │
└───────────┬─────────────┘   └─────────────┬─────────────┘
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

---

## 3. Target Enterprise Architecture

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
