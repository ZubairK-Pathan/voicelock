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
VoiceLock follows a strict incremental commit-and-push workflow for every completed task:
1. **Implement a small, coherent change.**
2. **Add or update targeted tests** covering happy paths, edge cases, and security boundaries.
3. **Run relevant tests and required regression checks** (`pytest`, `evaluate.py`, `tune_threshold.py`, `predict.py`).
4. **Review the diff and scan for secrets** (`firebase-credentials.json`, `.env`), biometric audio recordings, datasets, model caches, and generated artifacts.
5. **Update applicable project documentation** (`PROJECT_STATUS.md`, `CHANGELOG.md`, `SECURITY.md`, etc.).
6. **Commit using a clear conventional commit message.**
7. **Push the feature branch to GitHub:**
   ```bash
   git push -u origin feature/enterprise-foundation
   ```
8. **Verify remote synchronization** (ensure local HEAD matches remote branch commit).
9. **Report the commit hash, tests, and pushed branch before starting the next increment.**

**Safeguards:**
- Never push directly to `main`.
- Never force-push or rewrite published Git history.
- Never commit credentials, private keys, or biometric datasets.


