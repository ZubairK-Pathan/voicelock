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
# Run full automated test suite (35 tests)
pytest -v

# Run targeted test
pytest tests/test_api.py -k test_verify_real_audio_success
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
- **No Mock Predictions in Production:** Always route real inference through `predict_speaker` / `verify_speaker`.
- **Preserve Error Handling:** Do not call `sys.exit()` in code imported by web frameworks; raise custom exceptions instead.
- **Never Hardcode Secrets:** Use `.env` and environment variables. Verify changes with `git status` and `git diff` before committing.
