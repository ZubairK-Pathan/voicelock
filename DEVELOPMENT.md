# Development Guide — VoiceLock Enterprise

## 1. Prerequisites
- **macOS** or **Linux**
- **Python 3.10+** (Active environment is Python 3.14.7)
- **FFmpeg 6.0+** (`brew install ffmpeg` on macOS, or `apt-get install -y ffmpeg` on Linux)
- **Node.js 20+** & **npm 10+** (Active is Node v25.9.0, npm 11.12.1)
- **Docker & Docker Compose** (for local PostgreSQL instance)

---

## 2. Environment Setup
```bash
# Navigate to project directory
cd ~/Projects/Machine_learning/Voice\ Recognition

# Activate virtual environment
source .venv/bin/activate

# Install baseline dependencies
pip install -r requirements.txt

# Create local environment configuration
cp .env.example .env
```

---

## 3. Running Applications Locally

### Streamlit Web Application (Reference UI)
```bash
streamlit run app.py
```
*Accessible at `http://localhost:8501`.*

### FastAPI Inference Server
Run via the legacy entry point (100% backward-compatible):
```bash
uvicorn cloud_api:app --host 0.0.0.0 --port 8000 --reload
```
Or run directly via the new modular application package:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
*Interactive Swagger docs available at `http://localhost:8000/docs`.*

---

## 4. Running Tests & Baseline Verification

```bash
# Run full automated test suite (107 tests)
pytest -v

# Run targeted test suites
pytest tests/test_api.py -v          # Baseline API contracts and upload limits (35 tests)
pytest tests/test_auth.py -v         # Firebase Auth, RBAC, and WebSocket security (22 tests)
pytest tests/test_auth_policy.py -v  # Policy matrix and identity separation (7 tests)
pytest tests/test_device_auth.py -v  # IoT HMAC, ASGI limiter, CORS, rate limits (30 tests)
pytest tests/test_database.py -v     # Database configuration, pooling, and Alembic (13 tests)
```

## 5. Running ML Scripts & Baseline Evaluation
```bash
# Speaker identification on a single audio file
python predict.py "processed_dataset/Zubair/Zubair_Enrollment_R01.wav"

# Full baseline evaluation across test split
python evaluate.py

# Threshold calibration (EER analysis)
python tune_threshold.py

# Liveness detection on an audio sample
python liveness.py "processed_dataset/Zubair/Zubair_Enrollment_R01.wav"
```

---

## 6. Coding Standards & Safety
- **No Mock Predictions in Production Paths:** Always route real biometric workflows through `predict_speaker` / `verify_speaker`.
- **Preserve Error Handling:** Do not call `sys.exit()` in code imported by web frameworks; raise custom exceptions instead.
- **Never Hardcode Secrets:** Use `.env` and environment variables. Verify changes with `git status` and `git diff` before committing.
- **Fail-Closed Principle:** Startup and authentication checks fail safely on missing or invalid configuration.

---

## 7. IoT Device & Web Authentication Testing Guidelines
- **Identity Separation:** Never treat a Firebase User ID (`uid`) as a speaker voiceprint name, and never treat an IoT `device_id` as proof of identity without cryptographic authentication.
- **Testing IoT Device Authentication:**
  - Devices authenticate using either:
    1. Replay-resistant HMAC-SHA256 headers (`X-Device-ID`, `X-Device-Timestamp`, `X-Device-Nonce`, `X-Device-Signature`).
    2. Pre-shared secret key (`X-Device-Key`).
  - Device test registry can be injected outside production via `set_test_device_registry({"esp32-portal": {"secret": "...", "name": "..."}})`.
- **CORS Configuration:**
  - Configured via `ALLOWED_CORS_ORIGINS` (comma-separated origins).
  - Defaults to local development ports (3000, 5173, 8501).
  - Wildcard `*` with credentials enabled is strictly prohibited.
- **ASGI Stream Limiter:**
  - Raw body stream inspection rejects payloads > 10MB + 64KB for uploads and > 1MB for non-upload endpoints prior to multipart parsing.
- **Rate Limiting:**
  - Enforced via sliding-window `InMemoryRateLimiter` on `/challenge` (30/min), `/verify` (30/min), and `/identify` (15/min).
  - Biometric inference concurrency is bounded to 4 parallel slots. WebSocket sessions are capped at 100 frames and 300 seconds maximum duration.

---

## 8. Database Management & Alembic Migrations
- **Configuration:** Set `DATABASE_URL` in `.env`.
  - In development/testing: Defaults to local SQLite (`sqlite:///./voicelock.db`).
  - In production: PostgreSQL (`postgresql+psycopg://user:password@host:port/dbname`). Missing `DATABASE_URL` raises `RuntimeError`.
- **Applying Migrations:**
  ```bash
  alembic upgrade head
  ```
- **Rolling Back Migrations:**
  ```bash
  alembic downgrade -1     # Roll back single revision
  alembic downgrade base   # Roll back all revisions
  ```
- **Creating Migrations:**
  ```bash
  alembic revision --autogenerate -m "describe migration"
  ```
- **Testing Details:**
  - Automated tests in `tests/test_database.py` run against in-memory SQLite and a disposable temporary SQLite file.
  - PostgreSQL pooling (`QueuePool`), timeout, and URL normalization are verified via mock configurations. Production PostgreSQL instances should be validated prior to multi-worker deployment.

---

## 9. Incremental Delivery & GitHub Synchronization Policy
VoiceLock enforces a standing incremental commit-and-push workflow for every small, completed logical increment to build a robust and verifiable GitHub contribution history:

### Incremental Protocol Rules:
1. **Divide into Small Increments:** Break each milestone into small, independently testable units (e.g. 3C.2a schema, 3C.2b repository, 3C.2c authorization). Never batch entire milestones into single large commits.
2. **Execute Increment Workflow:**
   a. Implement one coherent piece of functionality.
   b. Add or update targeted unit and integration tests.
   c. Run the targeted tests.
   d. Run relevant regression checks (`pytest`, `evaluate.py`, `tune_threshold.py`, `predict.py`).
   e. Review the complete diff.
   f. Scan for secrets (`firebase-credentials.json`, `.env`), biometric audio recordings, datasets, model caches, and generated artifacts.
   g. Update applicable project documentation (`PROJECT_STATUS.md`, `CHANGELOG.md`, `SECURITY.md`, etc.).
   h. Create a meaningful conventional commit (e.g. `feat(database): define speaker registry schema and migration`).
   i. **PUSH THAT COMMIT TO GITHUB IMMEDIATELY:**
      ```bash
      git push -u origin feature/enterprise-foundation
      ```
   j. Verify remote synchronization (`git rev-parse HEAD == git rev-parse origin/feature/enterprise-foundation`).
   k. Report the commit hash and successful push before proceeding.
3. **No Batching:** Do not wait until the entire milestone is complete to push.
4. **Strict Sequencing:** Do not start the next logical increment until the current increment has been committed, pushed, and verified.
5. **No Broken Pushes:** If any test fails, resolve the issue before pushing. Never push knowingly broken increments.
6. **Push Failure Handling:** If a push fails, halt and diagnose the issue immediately. Do not proceed to subsequent increments without publishing the current one.
7. **Official Authentication:** If GitHub credentials expire, request official authentication flow. Never prompt for plaintext tokens, passwords, or keys in chat.
8. **Genuine Contributions:** Never create empty, artificial, or duplicate commits. Every commit must reflect genuine, reviewed code or documentation.
9. **Git Safeguards:** Never push directly to `main`, force-push (`--force`), or rewrite remote history.
10. **Data Protection:** Never commit secrets, service account credentials, biometric audio, or dataset files.
11. **Compatibility Preservation:** Preserve Streamlit reference implementation and existing security boundaries.
12. **Start-of-Session Verification:** Always verify current branch, local HEAD, remote HEAD, and working-tree cleanliness before initiating changes.
13. **End-of-Increment Reporting:** Detail increment name, files changed, tests run, commit hash, remote branch, and verification status.
14. **Doc Synchronization:** Maintain `AGENTS.md` and `DEVELOPMENT.md` alignment with this policy.
15. **Cost Controls:** Never provision billable cloud resources without explicit approval.


