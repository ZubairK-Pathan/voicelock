# Shared AI Engineering Guidelines — VoiceLock Enterprise

This file establishes the operational protocols and safety requirements for all AI software engineers (Antigravity, OpenAI Codex, or others) working on this repository.

---

## 1. Source of Truth & Session Resumption Protocol
When starting any turn or taking over a session:
1. **Always read this file (`AGENTS.md`) first.**
2. **Read `PROJECT_STATUS.md`** to identify the latest verified milestone, completed tasks, known issues, and next tasks.
3. **Inspect the actual repository state:**
   ```bash
   git status
   git branch -a
   git log -n 5 --oneline
   ```
4. Verify code and test status rather than blindly trusting prior conversational memory.
5. Work in small, independently verifiable milestones. Never rewrite entire systems in a single unreviewed action.

---

## 2. Non-Negotiable ML Preservation Rules
1. **Model Architecture:** SpeechBrain ECAPA-TDNN (`spkrec-ecapa-voxceleb`). Do not replace this model or retrain it without explicit approval.
2. **Biometric Embeddings:** 192-dimensional vector representations. Do not change vector dimensions or normalizations.
3. **Audio Preprocessing:** 16,000 Hz, mono (1 channel), peak-normalized to `[-1, 1]`. Preserved in `audio_utils.py`.
4. **Speaker Profiles:** Saved in `speaker_profiles/profiles.pkl` (dict mapping speaker names to 192-d vectors). Never delete or overwrite profiles without verified backup and approval.
5. **Threshold Calibration:** Do not change `DEFAULT_THRESHOLD` in `predict.py` without explicit approval and statistical validation.
6. **No Mocking in Production Paths:** Real SpeechBrain inference and Vosk transcription must run for actual biometric workflows. Isolated tests may use mocks only when explicitly labeled as unit tests.

---

## 3. Secret & Credential Safety
1. **Never commit secrets:** Service account keys (`firebase-credentials.json`), `.env` files, API tokens, and private keys must remain excluded via `.gitignore`.
2. **Never print secrets in logs or responses:** Avoid dumping JSON contents of credential files or printing private keys to stdout.
3. **Use `.env.example`** as the template for environment configuration.
4. **Git push precaution:** Always inspect `git diff --cached` or `git log origin/main..HEAD` before pushing.

---

## 4. Automation & Tooling Principles
1. **Prefer the terminal/CLI** for running tests, inspections, and builds rather than asking the user to run them manually.
2. **Run non-destructive commands:** Never run `git reset --hard`, `git clean -fd`, or discard stashes without explicit user authorization.
3. **Verification Requirement:** Never report that a test or build passed unless the command was executed and exited with return code 0.

---

## 5. Standard Commands
```bash
# Activate virtual environment
source .venv/bin/activate

# Run evaluation baseline
python evaluate.py

# Run threshold calibration
python tune_threshold.py

# Run inference test
python predict.py "processed_dataset/Zubair/Zubair_Enrollment_R01.wav"

# Run Streamlit reference app
streamlit run app.py

# Run FastAPI server
uvicorn cloud_api:app --host 0.0.0.0 --port 8000

# Apply database migrations
alembic upgrade head

# Rollback latest database migration
alembic downgrade -1

# Run database foundation tests
pytest tests/test_database.py -v
```

---

## 6. Incremental Delivery and GitHub Synchronization Protocol
This protocol is a permanent requirement for all VoiceLock development sessions to maintain a steady, meaningful GitHub contribution graph.

### Core Workflow Rules:
1. **Divide into Small Increments:** Break each milestone into small, independently testable increments. Never implement an entire milestone in one enormous batch if it can reasonably be divided.
2. **Execute Increment Workflow:**
   a. Implement one coherent piece of functionality.
   b. Add or update targeted tests covering happy paths, edge cases, and security boundaries.
   c. Run the targeted tests.
   d. Run relevant regression checks (`pytest`, `evaluate.py`, `tune_threshold.py`, `predict.py`).
   e. Review the complete diff.
   f. Scan for secrets, credentials, `.env` files, biometric audio, datasets, speaker profiles, model caches, and generated artifacts.
   g. Update applicable project documentation (`PROJECT_STATUS.md`, `CHANGELOG.md`, etc.).
   h. Create a meaningful conventional commit.
   i. **PUSH THAT COMMIT TO GITHUB IMMEDIATELY:**
      ```bash
      git push -u origin feature/enterprise-foundation
      ```
   j. Verify remote synchronization (`git rev-parse HEAD == git rev-parse origin/feature/enterprise-foundation`).
   k. Report the commit hash and successful push before proceeding.
3. **No Batching:** Do not wait until the entire milestone is complete to push.
4. **Strict Sequence:** Do not start the next logical increment until the current increment has been committed, pushed, and verified.
5. **No Broken Pushes:** If a test fails, fix it before pushing. Never knowingly push a broken increment merely to increase contribution activity.
6. **Push Failure Diagnostics:** If a push fails, stop and diagnose the issue immediately. Do not silently continue building further increments without publishing the completed one.
7. **Auth Handling:** If GitHub authentication expires, request completion of the official flow. Never ask the user to paste passwords, OTPs, tokens, or private keys into chat.
8. **No Artificial Commits:** Never use empty commits, meaningless changes, duplicate commits, or fabricated work to manipulate contribution statistics. Every commit must represent a real, reviewed change.
9. **Git Safety:** Never push directly to `main`, force-push (`--force`), rewrite history, or discard existing work without explicit authorization.
10. **Data Hygiene:** Never commit secrets (`firebase-credentials.json`, `.env`), biometric recordings, datasets, or local credentials.
11. **Compatibility Preservation:** Preserve the working Streamlit reference implementation and do not weaken Firebase authentication or device authentication.
12. **Start-of-Session Verification:** Verify actual repository state, current branch, local HEAD, remote HEAD, and working-tree status before starting work. Never assume a previous push succeeded without checking.
13. **End-of-Increment Reporting:** At the end of each increment, provide:
    - Increment name
    - Files and functionality changed
    - Tests executed and results
    - Commit hash and subject
    - Remote branch pushed
    - Confirmation that remote HEAD matches local HEAD
    - Any remaining issues
14. **Documentation Synchronization:** Keep `AGENTS.md` and `DEVELOPMENT.md` synchronized with this policy at all times.
15. **Cost & Infrastructure Safeguards:** Never provision billable cloud resources without explicit approval.

