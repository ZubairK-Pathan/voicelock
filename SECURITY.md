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
4. **Session & Speaker Binding:** Challenges are bound to a client `session_id` and optionally to `claimed_identity`. Requests with mismatched session IDs or claimed identities are rejected with HTTP 400.
5. **Fail-Closed Execution:** If liveness transcription fails (empty audio, unrecognized speech, or mismatched digits), the API fails closed, returns `action: DENY`, and strictly skips expensive biometric inference.
6. **In-Memory Store Scope & Production Limitations:** The current `InMemoryChallengeStore` is thread-safe within a single Python process. In multi-worker (`--workers > 1`) or distributed horizontal environments, an external distributed store (Redis / PostgreSQL) implementing `BaseChallengeStore` must be used.
7. **Public Exposure Warning:** Endpoints `/identify`, `/verify`, and `/challenge` are currently unauthenticated. Public exposure is strictly prohibited until API token authentication and rate limiting are implemented.

---

## 4. Secret Handling Rules
- Never commit `firebase-credentials.json`, `.env`, private keys (`*.key`, `*.pem`), or database passwords.
- Run `git status` and `git diff --staged` before every commit to inspect for accidental credential inclusion.
- If credentials are ever pushed to a public remote, immediately revoke and rotate the affected keys in the Firebase/GCP Console.


