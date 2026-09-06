<h1 align="center">VoiceLock 🔐<br>Voice-Based Biometric Access Control System</h1>

<p align="center">
  A state-of-the-art Speaker Identification & Verification system. <br>
  Built with <strong>Python, SpeechBrain, ECAPA-TDNN, and FastAPI</strong> with a beautiful <strong>Streamlit</strong> web UI.
</p>

---

## 📖 Overview

VoiceLock is an end-to-end speaker recognition system designed for smart locks, banking authentication, or enterprise badge systems. It is robust, lightweight (can run inference on IoT edge servers or free cloud tiers), and highly secure against replay attacks (voice spoofing).

### ✨ Key Features

1. **Speaker Identification (1-to-N):** Identifies *who* is speaking from a database of enrolled users.
2. **Speaker Verification (1-to-1):** Verifies if a user is *who they claim to be*.
3. **Anti-Spoofing (Liveness Detection):** Prevents replay attacks (playing a pre-recorded voice note from WhatsApp) by issuing a random 3-digit on-screen challenge that the user must read aloud. Verified using Vosk's offline Speech-To-Text engine.
4. **Live Enrollment:** Users can enroll themselves via their microphone directly in the app.
5. **IoT & Cloud Ready:** Features a FastAPI backend (`cloud_api.py`) exposing HTTP REST and WebSockets endpoints, making it ready to integrate with ESP32 or Raspberry Pi edge devices.
6. **EER-Optimized Thresholds:** The acceptance threshold isn't guessed; it is mathematically derived using Equal Error Rate (EER) Analysis.

---

## 🧠 System Architecture & Pipeline

### 1. The ML Engine (ECAPA-TDNN)
We use the **ECAPA-TDNN** (Emphasized Channel Attention, Propagation and Aggregation in Time-Delay Neural Networks) model, sourced from `SpeechBrain`, pretrained on the VoxCeleb dataset (7,000+ speakers). 
Unlike simple energy/amplitude detectors, ECAPA-TDNN extracts a **192-dimensional embedding** (a voiceprint) that mathematically represents the unique geometric structure of a person's vocal tract.

### 2. The Liveness Engine (Anti-Spoofing)
Voice biometrics are vulnerable to replay attacks. We mitigate this using a **Challenge-Response** flow:
- The system generates a random 3-digit code (e.g., `5 2 9`).
- The user must speak it.
- We use the **Vosk** offline acoustic model (~40MB) to transcribe the digits.
- If the digits match, liveness is proven, and the voice is passed to the ECAPA-TDNN for identity verification.

### 3. Verification Protocol (Cosine Similarity)
When a user attempts to authenticate, their new 192-d voiceprint is compared against their saved, enrolled voiceprint using **Cosine Similarity**. If the angle between the vectors results in a score higher than our calibrated threshold, access is granted.

---

## 🚀 How to Run Locally

### Prerequisites
- Python 3.10+
- `ffmpeg` installed on your machine (`brew install ffmpeg` on macOS, or `sudo apt install ffmpeg` on Linux).

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/voicelock.git
   cd voicelock
   ```

2. **Set up the virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

### Running the Web UI (Streamlit)
To interact with the full system (Enrollment, Identification, Verification, and Liveness):
```bash
source .venv/bin/activate
streamlit run app.py
```
*The app will automatically open at `http://localhost:8501`*

---

## ☁️ Running the Cloud IoT API

For integrating with hardware (like an ESP32 door lock), you don't run Streamlit. Instead, run the headless FastAPI server.

```bash
uvicorn cloud_api:app --host 0.0.0.0 --port 8000
```
- **HTTP POST `/identify`**: Send a `.wav` file, get back the predicted speaker.
- **HTTP POST `/verify`**: Send a `.wav` file and `claimed_identity`. Returns `{"accepted": true/false}`.
- *Check `CLOUD_SETUP.md` for a full guide on deploying this to Oracle Cloud's Free Tier and writing MicroPython code for the ESP32.*

---

## 🔬 Research & Analytics

### Equal Error Rate (EER) Calibration
Run `python tune_threshold.py` to analyze the biometric performance of the enrolled users. It generates ROC and DET curves, and calculates the precise threshold where the False Acceptance Rate (FAR) equals the False Rejection Rate (FRR).

### Fine-Tuning Findings
We conducted a fine-tuning experiment (`train.py`) using ArcFace (AAM-Softmax) loss on a small, 3-speaker dataset. 
**Finding:** Fine-tuning a deep network on a tiny dataset causes severe overfitting (0.00% EER on the training set, but poor generalization). Therefore, for small-scale access control systems, **Vector Enrollment** (using the pretrained model as a frozen feature extractor and averaging 5 live samples) is the mathematically superior and most robust approach.

---

## 📂 Project Structure

- `app.py`: The modern Streamlit Web Dashboard.
- `audio_utils.py`: Core logic for embeddings, model loading, and Cosine Similarity.
- `liveness.py`: Challenge-response anti-spoofing mechanism via Vosk.
- `cloud_api.py`: FastAPI server for IoT hardware integration.
- `predict.py`: Standalone scripts for 1-to-N and 1-to-1 matching.
- `tune_threshold.py`: Biometric statistical evaluation scripts.
- `preprocess.py`: Audio standardization (converts m4a/mp3 to 16kHz mono WAV).

---

> *Developed as a Final Year Computer Science Engineering Project.*
