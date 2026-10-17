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
