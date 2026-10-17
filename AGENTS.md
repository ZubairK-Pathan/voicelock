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
```

---

## 6. Incremental Delivery and GitHub Synchronization Protocol
For every completed, logically separate increment:
1. **Implement a small, coherent change.**
2. **Add or update targeted tests.**
3. **Run relevant tests and required regression checks.**
4. **Review the diff and scan for secrets and sensitive data.**
5. **Update applicable project documentation.**
6. **Commit using a clear conventional commit message.**
7. **Push the feature branch to GitHub:**
   ```bash
   git push -u origin feature/enterprise-foundation
   ```
8. **Verify remote synchronization** (ensure local HEAD matches remote branch commit).
9. **Report the commit hash, tests, and pushed branch before starting the next increment.**

### Prohibitions & Safeguards:
- Never commit or push knowingly failing tests, secrets (`firebase-credentials.json`, `.env`), biometric audio recordings, datasets, model caches, or local credentials.
- Never push directly to `main`, force-push (`--force`), rewrite history, or provision billable cloud resources without explicit approval.
- If an increment fails: fix it before pushing, or leave the work uncommitted and report why. Do not manufacture artificial commits just to increase contribution counts.

