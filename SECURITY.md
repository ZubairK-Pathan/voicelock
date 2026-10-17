# Security Policy & Architecture — VoiceLock Enterprise

## 1. Threat Model & Countermeasures

| Threat Vector | Description | Countermeasure / Mitigation |
| :--- | :--- | :--- |
| **Replay Attacks** | Attacker plays a pre-recorded voice sample of an authorized user. | Digit-based challenge-response liveness check verified via Vosk STT. |
| **Voice Cloning / Deepfakes** | Attacker generates synthetic voice audio using generative AI. | Challenge-response adds prompt unpredictable latency; future work includes acoustic phase artifact detection. Limitations acknowledged: challenge-response does not defeat real-time low-latency voice conversion. |
| **Impostor Voice Matches** | Unauthorized speaker attempts to claim an authorized identity. | 192-dimensional ECAPA-TDNN embedding comparison with cosine similarity thresholding. |
| **Client Threshold Tampering** | Attacker overrides threshold in form data to force acceptance. | Enforce threshold verification strictly on the server; remove all client-supplied threshold parameters from public API routes. |
| **Denial of Service (DoS)** | Attacker uploads huge audio files or floods endpoints. | Implement strict upload size limits (`MAX_AUDIO_SIZE_BYTES = 10MB`) and rate limiting middleware. |
| **API Denial of Service via `sys.exit()`** | Missing files cause process termination. | Eliminate `sys.exit()` calls from library modules; replace with typed HTTP exceptions. |
| **Credential & Key Leakage** | Leaking service account keys to public version control. | Enforce strict `.gitignore` rules, provide sanitized `.env.example`, and isolate secrets to local configuration. |

---

## 2. Liveness Challenge Security Requirements
1. **Cryptographically Secure Randomness:** Must use `secrets.randbelow` (or CSPRNG), not `random.randint`.
2. **Short Time-to-Live (TTL):** Challenges must expire within 60 seconds of issuance.
3. **Single-Use Invalidation:** A challenge nonce must be consumed upon first evaluation and cannot be reused.
4. **Session Binding:** Challenges must be cryptographically bound to the requesting user session or registered IoT device ID.

---

## 3. Secret Handling Rules
- Never commit `firebase-credentials.json`, `.env`, private keys (`*.key`, `*.pem`), or database passwords.
- Run `git status` and `git diff --staged` before every commit to inspect for accidental credential inclusion.
- If credentials are ever pushed to a public remote, immediately revoke and rotate the affected keys in the Firebase/GCP Console.
