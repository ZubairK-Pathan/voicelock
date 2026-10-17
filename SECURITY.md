# Security Policy & Architecture — VoiceLock Enterprise

## 1. Threat Model & Countermeasures

| Threat Vector | Description | Countermeasure / Mitigation |
| :--- | :--- | :--- |
| **Replay Attacks** | Attacker plays a pre-recorded voice sample of an authorized user. | Digit-based challenge-response liveness check verified via Vosk STT. |
| **Voice Cloning / Deepfakes** | Attacker generates synthetic voice audio using generative AI. | Challenge-response adds prompt unpredictable latency; future work includes acoustic phase artifact detection. Limitations acknowledged: challenge-response does not defeat real-time low-latency voice conversion. |
| **Impostor Voice Matches** | Unauthorized speaker attempts to claim an authorized identity. | 192-dimensional ECAPA-TDNN embedding comparison with cosine similarity thresholding. |
| **Client Threshold Tampering** | Attacker overrides threshold in form data to force acceptance. | Enforce threshold verification strictly on the server (`load_server_threshold()` bounded in `[0.0, 1.0]`); disallow client-supplied threshold override; verified that impostor score (0.15) cannot flip to UNLOCK when client supplies `threshold=0.01`. |
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

## 3. Liveness Challenge Security Requirements
1. **Cryptographically Secure Randomness:** Must use `secrets.randbelow` (or CSPRNG), not `random.randint`.
2. **Short Time-to-Live (TTL):** Challenges must expire within 60 seconds of issuance.
3. **Single-Use Invalidation:** A challenge nonce must be consumed upon first evaluation and cannot be reused.
4. **Session Binding:** Challenges must be cryptographically bound to the requesting user session or registered IoT device ID.

---

## 4. Secret Handling Rules
- Never commit `firebase-credentials.json`, `.env`, private keys (`*.key`, `*.pem`), or database passwords.
- Run `git status` and `git diff --staged` before every commit to inspect for accidental credential inclusion.
- If credentials are ever pushed to a public remote, immediately revoke and rotate the affected keys in the Firebase/GCP Console.

