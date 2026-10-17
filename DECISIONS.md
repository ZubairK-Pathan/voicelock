# Architecture Decision Records (ADRs) — VoiceLock Enterprise

---

## ADR 001: Git Credential Containment & Soft Reset
* **Status:** Proposed / Pending Approval
* **Context:** A local commit (`310e8df`) added `firebase-credentials.json` directly into Git on the local `main` branch. This commit has not been pushed to `origin/main`.
* **Decision:**
  1. Add `firebase-credentials.json` to `.gitignore`.
  2. Create `.env.example` with sanitized placeholders.
  3. Execute `git reset --soft HEAD~1` to move `main`'s HEAD back to `origin/main` (`9587b59`), leaving all working tree files intact.
  4. Ensure `firebase-credentials.json` remains untracked on disk.
* **Consequences:** Prevents exposing Firebase service account keys on public GitHub without modifying or deleting local credentials.

---

## ADR 002: Statistical Validity Analysis of Reported EER & Threshold Retention
* **Status:** Accepted
* **Context:** `tune_threshold.py` reports an Equal Error Rate (EER) of `0.00%` at threshold `0.6807`. In contrast, `predict.py` and `cloud_api.py` use `DEFAULT_THRESHOLD = 0.25`.
* **Inspection Findings:**
  1. The test dataset defined in `split_info.json` comprises only **3 speakers** (`Advait`, `Omar`, `Parth`) across **27 test audio files**.
  2. The remaining 9 enrolled speakers were registered later and have no test entries in `all_embeddings.pkl`.
  3. The reported 0.00% EER is an artifact of small sample size (n=27 genuine pairs), not evidence of a generalizable zero-error rate in diverse environments.
  4. Immediately shifting `DEFAULT_THRESHOLD` from `0.25` to `0.68` without validation on a broader acoustic dataset risks causing severe False Rejections for genuine users under real microphone variations.
* **Decision:** Preserve `DEFAULT_THRESHOLD = 0.25` as the baseline setting. Make the threshold configurable via environment variables (`DEFAULT_THRESHOLD`), and design an expanded multi-speaker validation protocol before adjusting default biometric thresholds.

---

## ADR 003: Relational PostgreSQL Persistence vs. Firestore
* **Status:** Accepted
* **Context:** A previous stash experiment (`database.py`) prototyped storing serialized vector embeddings directly in Cloud Firestore. The master mandate requests PostgreSQL with migrations.
* **Decision:** Use PostgreSQL (managed via SQLAlchemy and Alembic migrations) for relational access control entities: Users, Roles, Devices, Challenge Sessions, Audit Logs, and Profile Metadata.
* **Biometric Artifact Strategy:** Store 192-d vectors as binary arrays or versioned serialized files with cryptographic checksums and references stored in PostgreSQL. Avoid storing large raw audio clips in the database.

---

## ADR 004: SpeechBrain CPU Execution Strategy
* **Status:** Accepted
* **Context:** SpeechBrain 1.1.0 does not natively support PyTorch MPS (`mps`) device types on Apple Silicon and crashes if forced to MPS.
* **Decision:** Force `device="cpu"` in `load_embedding_model()`. The ECAPA-TDNN model is compact (~7M parameters) and completes CPU inference in ~1.5 seconds, ensuring universal compatibility across macOS local environments and Linux Docker containers.

---

## ADR 005: Incremental API Modularization & Early Challenge Invalidation
* **Status:** Accepted
* **Context:** `cloud_api.py` was a monolithic 478-line script containing configuration parsers, model caches, upload spooling logic, and all HTTP/WebSocket endpoints. Furthermore, during verification, audio uploads were streamed and written to temporary files before verifying whether the submitted challenge ID was valid, resulting in unnecessary disk I/O on invalid requests.
* **Decision:**
  1. Modularize the FastAPI application into the standard enterprise `app/` package:
     - `app/core/config.py` & `app/core/errors.py`: Configuration and HTTP error handling.
     - `app/schemas/`: Pydantic data schemas for validation and API contracts.
     - `app/services/`: Single-responsibility service layer (`speaker_service`, `challenge_service`, `verification_service`).
     - `app/api/`: Sub-routers for health, speakers, challenges, and verification.
     - `app/main.py`: Application factory (`create_app`) with modern FastAPI lifespan management.
  2. Maintain `cloud_api.py` as a 100% backward-compatible entry point re-exporting all public functions and models.
  3. Implement dynamic accessor functions in `app/api/` (`_get_system()`, `_get_challenge_store()`, etc.) that inspect `sys.modules.get("cloud_api")`, preserving full compatibility with legacy `unittest.mock.patch("cloud_api.*")` calls without introducing circular dependencies.
  4. In `POST /verify`, atomically validate and consume the liveness challenge *before* calling `save_upload()`, rejecting invalid, expired, reused, or session-mismatched challenges upfront with HTTP 400 before payload spooling or disk I/O.
* **Consequences:** Provides clean architectural separation and service extensibility while preserving identical HTTP contracts, full backward compatibility, and zero regressions across all 35 automated tests.

---

## ADR 006: Identity Separation & Dual-Credential Authentication Architecture
* **Status:** Accepted
* **Context:** The system requires authentication before exposing biometric verification, challenge generation, or directory queries to the network. Three fundamentally different entity types interact with the system: human operators using a web console, IoT physical kiosk terminals at doors, and human voiceprints. Conflating these three models (e.g. treating a Firebase UID as a voiceprint name, or treating a caller-supplied `session_id` or `device_id` as authentication) creates severe privilege escalation, spoofing, and enumeration vulnerabilities.
* **Decision:**
  1. **Strictly decouple three identity domains:**
     - `IdentityType.WEB_USER`: Human operator/employee authenticated via Firebase ID Tokens (RS256 JWT).
     - `IdentityType.IOT_DEVICE`: Hardware demonstration terminal authenticated via Pre-Shared Key / HMAC token (`X-Device-Key`).
     - `IdentityType.SPEAKER_VOICE`: Passive biometric credential evaluated via ECAPA-TDNN cosine similarity (>= 0.25) and Vosk liveness check.
  2. **Implement Role-Based Access Control (RBAC):**
     - `Role.ANONYMOUS`: Read-only health check (`/`).
     - `Role.DEVICE`: Bounded strictly to `POST /challenge` and `POST /verify`. Devices cannot list speakers, enroll voices, or change thresholds.
     - `Role.USER`: Standard authenticated employee. Can initiate self-verification.
     - `Role.ADMIN`: Security administrator. Can list speakers (`GET /speakers`), enroll voices, view audit logs, and invoke `POST /identify`.
  3. **Credential Handling:**
     - Firebase service account keys (`firebase-credentials.json`) must remain strictly untracked and excluded from version control via `.gitignore`.
     - In development, credentials are loaded via `FIREBASE_CREDENTIALS_PATH`.
     - For automated test suites, a mock token verification adapter will be provided when `VOICELOCK_ENV=testing`.
* **Consequences:** Eliminates unauthenticated access, protects biometric data from unauthorized directory queries, and provides a scalable, auditable security foundation for the frontend and hardware terminal.


