# Security Policy & Architecture — VoiceLock Enterprise

## 1. Threat Model & Countermeasures

| Threat Vector | Description | Countermeasure / Mitigation |
| :--- | :--- | :--- |
| **Replay Attacks** | Attacker plays a pre-recorded voice sample of an authorized user. | Stateful digit-based challenge-response liveness check verified via Vosk STT. Enforces unpredictable CSPRNG digits (`secrets.randbelow`), 60s TTL, single-attempt invalidation ('burn-on-use'), and session/identity binding. |
| **Voice Cloning / Deepfakes** | Attacker generates synthetic voice audio using generative AI. | Challenge-response adds unpredictable dynamic latency to frustrate pre-computed audio. **Explicit Limitation:** Random spoken digits do NOT defeat real-time low-latency voice cloning or generative audio streaming. Future milestones will explore acoustic phase and spectral artifact analysis. |
| **Impostor Voice Matches** | Unauthorized speaker attempts to claim an authorized identity. | 192-dimensional ECAPA-TDNN embedding comparison with cosine similarity thresholding. |
| **Client Threshold Tampering** | Attacker overrides threshold in form data to force acceptance. | Enforce threshold verification strictly on the server (`load_server_threshold()` bounded in `[0.0, 1.0]`); client-supplied threshold parameters are ignored; verified that impostor score (0.15) cannot flip to UNLOCK when client supplies `threshold=0.01`. |
| **Challenge Replay & Race Conditions** | Attacker re-submits a previously intercepted challenge or concurrent duplicate requests. | Single-Attempt Invalidation ('burn-on-use') via thread-locked atomic state transition in `BaseChallengeStore`. Exactly 1 request succeeds in consuming a challenge; all subsequent or concurrent submissions are rejected with HTTP 400. |
| **Denial of Service (DoS via Uploads)** | Attacker uploads huge audio files or floods endpoints. | Implement upfront `Content-Length` header inspection and 64KB chunked streaming upload ceilings (`MAX_AUDIO_SIZE_BYTES = 10MB`, HTTP 413) to reject oversized payloads before buffering or inference. |
| **Malformed / Non-Audio Payloads** | Attacker uploads corrupt files or non-audio streams disguised as `.wav`. | Catch decoding exceptions (`soundfile.LibsndfileError`, FFmpeg conversion failure) and return HTTP 400 Bad Request rather than uncaught 500 crashes. Guaranteed `try/finally` cleanup removes temporary files. |
| **API Denial of Service via `sys.exit()`** | Missing files cause process termination. | Eliminate `sys.exit()` calls from library modules; replace with typed HTTP exceptions (`FileNotFoundError`, `ValueError`). |
| **Credential & Key Leakage** | Leaking service account keys to public version control. | Enforce strict `.gitignore` rules, provide sanitized `.env.example`, and isolate secrets to local configuration. |

---

## 2. Threshold Calibration & Biometric Integrity Policy
- **Calibration Status:** Current baseline threshold is `0.25`.
- **EER Validity Warning:** Statistical evaluation on held-out test splits reveals that the 0.00% EER is derived from only 3 speakers (Advait, Omar, Parth) across 27 samples. Changing the baseline threshold to 0.68 based solely on this limited sample would risk high False Rejection Rates (FRR) in production acoustic conditions.
- **Server Authority:** The server threshold is independently validated and cannot be lowered by client request parameters.

---

## 3. Liveness Challenge Security Requirements & State Machine
1. **Cryptographically Secure Randomness:** Digit generation uses `secrets.randbelow(10)` (CSPRNG), not `random.randint`. Challenge IDs use `secrets.token_hex(16)`.
2. **Short Time-to-Live (TTL):** Challenges expire strictly after 60 seconds.
3. **Single-Attempt Invalidation ('Burn-on-Use'):** A challenge transitions from `PENDING` to `CONSUMED` immediately upon verification initiation, regardless of whether speech or biometric checks succeed. This prevents brute-force attempts and replay attacks against active tokens.
4. **Early Invalidation & Resource Exhaustion Defense:** In `POST /verify`, the challenge is atomically validated and consumed *before* spooling or writing audio uploads to disk. If the challenge is missing, expired, reused, or session-mismatched, the request fails immediately with HTTP 400 before any audio file I/O or buffering occurs.
5. **Caller-Supplied Session IDs as Ephemeral Correlation Tokens (Not Authentication):**
   - *Security Clarification:* A client-provided `session_id` is an ephemeral correlation handle to bind challenge generation to a verification submission. It does **not** constitute cryptographically verified principal authentication or user identity.
   - *Risk:* If a client generates its own `session_id`, an attacker who intercepts or predicts this token could potentially associate requests. Unpredictable 128-bit challenge IDs mitigate guessing, but session tokens do not replace authentication.
   - *Requirement:* In production deployments, verification must bind to an authenticated principal identity (e.g., Firebase Auth JWT or mutual TLS device identity). The unauthenticated API is strictly private to development and MUST NOT be exposed publicly.
6. **Session & Speaker Binding:** Challenges are bound to a client `session_id` and optionally to `claimed_identity`. Requests with mismatched session IDs or claimed identities are rejected with HTTP 400.
7. **Fail-Closed Execution:** If liveness transcription fails (empty audio, unrecognized speech, or mismatched digits), the API fails closed, returns `action: DENY`, and strictly skips expensive biometric inference.
8. **In-Memory Store Scope & Production Limitations:** The current `InMemoryChallengeStore` is thread-safe within a single Python process. In multi-worker (`--workers > 1`) or distributed horizontal environments, an external distributed store (Redis / PostgreSQL) implementing `BaseChallengeStore` must be used.
9. **Spoken Digit Protection Boundary:** Spoken 3-digit challenges mitigate static audio replay attacks, but do **not** provide complete protection against real-time, low-latency AI voice synthesis or deepfake streaming engines.
10. **Public Exposure Warning:** Endpoints `/identify`, `/verify`, and `/challenge` are currently unauthenticated. Public exposure is strictly prohibited until API token authentication and rate limiting are implemented.

---

## 4. Secret Handling Rules
- Never commit `firebase-credentials.json`, `.env`, private keys (`*.key`, `*.pem`), or database passwords.
- Run `git status` and `git diff --staged` before every commit to inspect for accidental credential inclusion.
- If credentials are ever pushed to a public remote, immediately revoke and rotate the affected keys in the Firebase/GCP Console.

---

## 5. Security Review Findings Ranked by Severity (Milestone 3A Audit)

| Severity | ID | Vulnerability / Threat | Impact & Attack Scenario | Remediation in Milestone 3B/3C |
| :--- | :--- | :--- | :--- | :--- |
| **CRITICAL** | `SEC-001` | **Unauthenticated Public Endpoints** | Endpoints `/identify`, `/verify`, `/challenge`, and `/speakers` accept unauthenticated requests. An external attacker can query the system, enumerate users, and invoke expensive biometric workflows. | Implement Firebase Admin SDK JWT bearer authentication for web clients and pre-shared cryptographic keys for IoT devices. |
| **CRITICAL** | `SEC-002` | **Directory Reconnaissance & Speaker Enumeration** | `GET /speakers` dumps all enrolled speaker names. Furthermore, `POST /challenge` with `claimed_identity` returns HTTP 404 if the speaker does not exist, enabling unauthenticated user enumeration. | Restrict `GET /speakers` to `Role.ADMIN`. Standardize `POST /challenge` error responses to prevent timing and status code enumeration. |
| **CRITICAL** | `SEC-003` | **Compute Engine Denial of Service (CPU Exhaustion)** | SpeechBrain ECAPA-TDNN feature extraction consumes ~1.5s CPU per utterance, and Vosk consumes ~0.3s. A flood of unauthenticated requests to `/identify` or `/verify` saturates CPU cores and starves legitimate door access. | Restrict endpoints to authenticated callers, add rate limiting middleware (slowapi), and introduce bounded inference concurrency semaphores. |
| **HIGH** | `SEC-004` | **Multipart Upload Buffering Vulnerability** | While `save_upload()` checks `Content-Length` and enforces byte ceilings, Starlette's `MultiPartParser` buffers uploads in memory (up to 1MB) and disk before route handlers execute. An attacker omitting `Content-Length` or using chunked encoding can force multi-gigabyte disk writes. | Implement an ASGI-level raw stream body size limiter middleware that terminates incoming connections exceeding `MAX_AUDIO_SIZE_BYTES` + 64KB margin prior to multipart parsing. |
| **HIGH** | `SEC-005` | **Unbounded Streaming & Memory Ingestion on WebSocket** | `/ws/identify` is completely unauthenticated. Audio frame size is checked *after* `websocket.receive_bytes()` buffers the payload in memory. Continuous frame streaming can cause memory exhaustion and CPU lockup. | Require authentication ticket/token on WebSocket handshake, enforce message-rate limits, and restrict streaming to `Role.ADMIN`. |
| **HIGH** | `SEC-006` | **Challenge Store Single-Process Boundary & Memory Flooding** | `InMemoryChallengeStore` is process-local. An unauthenticated attacker can spam `/challenge` to create thousands of challenge objects, consuming heap memory. Multi-worker Uvicorn setups cause state divergence. | Require authentication for challenge creation, apply per-client rate limits, and transition to shared atomic storage (Redis / PostgreSQL) in Milestone 3C. |
| **MEDIUM** | `SEC-007` | **Overly Permissive CORS Policy** | `app/main.py` configures `allow_origins=["*"]` with `allow_credentials=True`. This is insecure and violates modern browser CORS specifications when credentials are used. | Restrict CORS to explicit trusted domains via `ALLOWED_CORS_ORIGINS` environment variable. |
| **MEDIUM** | `SEC-008` | **Public Reconnaissance via Health Endpoint** | `GET /` currently exposes active `threshold` (0.25) and `enrolled_speakers` count without authentication. | Redact `threshold` and `enrolled_speakers` from unauthenticated `GET /`. Expose system metrics only to authenticated administrators. |
| **MEDIUM** | `SEC-009` | **EER Sample Size & Threshold Discordance** | Baseline threshold is 0.25, while maximum impostor similarity in the test set reached 0.6802. Reported 0.00% EER is derived from only 27 test recordings across 3 speakers. | Conduct a comprehensive biometric evaluation across all 12 enrolled speakers with multi-session acoustic diversity before production deployment. |
| **MEDIUM** | `SEC-010` | **Synthetic Voice / Real-Time Deepfake Vulnerability** | Spoken digit challenge-response mitigates pre-recorded static audio replay, but cannot defeat low-latency real-time voice cloning engines. | Document limitation; evaluate acoustic phase, spectral distortion, and dynamic challenge prompts in future research. |
| **LOW** | `SEC-011` | **Dynamic Test Adapter Fragility** | `sys.modules.get("cloud_api")` lookup pattern is non-standard. If future tests or services import `app` directly without `cloud_api`, patches on `cloud_api` will not apply. | Transition to standard FastAPI dependency injection (`Depends`) in future refactoring. |

---

## 6. Target Authentication & Authorization Architecture (Milestone 3B Implementation Blueprint)

### A. Firebase ID-Token Server-Side Verification:
1. **SDK:** Official `firebase-admin` (v7.7.0 installed).
2. **Signature & Cryptography:** Verified using Google's public JWKS certificates, rotated automatically by Google.
3. **Claims Validated:**
   - `iss`: Must equal `https://securetoken.google.com/<project_id>`
   - `aud`: Must equal `<project_id>`
   - `sub`: Non-empty Firebase UID string
   - `exp`: Must be in the future (1-hour standard lifetime)
   - `iat`: Must be in the past
4. **Revocation Checking:** `firebase_admin.auth.verify_id_token(token, check_revoked=True)` will be enforced for privileged administrative actions.
5. **Credential Management:**
   - Production: Application Default Credentials (ADC) or GCP service account.
   - Development: Untracked `firebase-credentials.json` loaded via `FIREBASE_CREDENTIALS_PATH`.
   - Mock Test Mode: Deterministic mock token verifier enabled only when `VOICELOCK_ENV=testing` for CI/CD and unit test suites.

### B. Hardware Device Authentication (ESP32):
1. **Authentication Scheme:** `X-Device-ID` and `X-Device-Key` headers.
2. **Key Storage:** Device keys hashed using SHA-256 with per-device salts, stored in PostgreSQL.
3. **Scope of Authority:** Bounded strictly to `POST /challenge` and `POST /verify`. Devices cannot query directories, enroll speakers, or view system analytics.


