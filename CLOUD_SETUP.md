# Cloud Deployment Guide — Speaker Recognition IoT System

## Architecture Overview

```
┌─────────────────────┐       HTTP POST /verify        ┌──────────────────────────┐
│   IoT Device        │  ────────────────────────────► │   Cloud Server           │
│  (ESP32 / RPi)      │  {"audio": <bytes>,             │  (FastAPI + ECAPA-TDNN)  │
│                     │   "claimed_identity": "Omar"}   │                          │
│  - Records audio    │                                 │  - Loads model once      │
│  - Sends HTTP POST  │ ◄──────────────────────────── │  - Runs inference        │
│  - Opens/keeps lock │  {"accepted": true,             │  - Returns JSON          │
│                     │   "score": 0.83,                │                          │
└─────────────────────┘   "action": "UNLOCK"}          └──────────────────────────┘
```

**Why Cloud?**
- ECAPA-TDNN needs ~200MB RAM for model weights — too much for ESP32 (520KB RAM)
- Raspberry Pi can run it locally, but cloud offloads compute and enables remote management
- Cloud also lets you update speaker profiles without physically touching the device

---

## Free Deployment Options (Compared)

| Platform | RAM | CPU | Free Tier? | Cold Start | Best For |
|---|---|---|---|---|---|
| **Oracle Cloud Free** | 24 GB | 4 ARM OCPUs | ✅ Always free | None | **Recommended** |
| **Hugging Face Spaces** | 16 GB | 2 vCPUs | ✅ Always free | ~5s on first hit | Quickest setup |
| **Render.com** | 512 MB | Shared | ✅ Free (sleeps 15min) | ~30s | Development only |
| **Railway** | 512 MB | Shared | ❌ $5/mo after trial | None | Small projects |
| **Google Cloud Run** | 4 GB | 2 vCPUs | ✅ 2M req/month free | ~3s | Scalable |

---

## Option 1 (Recommended): Oracle Cloud Always Free

**Best because:** 24GB RAM, no sleeping, no expiry, real Linux VM. Free forever.

### Setup Steps

```bash
# 1. Sign up: https://www.oracle.com/cloud/free/
# 2. Create an ARM (Ampere A1) Compute instance — choose Ubuntu 22.04
# 3. In security rules, open port 8000 (TCP ingress)
# 4. SSH into the VM

# 5. Install dependencies
sudo apt update && sudo apt install -y python3-pip ffmpeg git

# 6. Clone your project
git clone https://github.com/YOUR_USERNAME/voice-recognition.git
cd voice-recognition

# 7. Install Python requirements
pip install -r requirements.txt
pip install fastapi uvicorn python-multipart

# 8. Copy your speaker_profiles/ folder to the VM
scp -r speaker_profiles/ ubuntu@YOUR_VM_IP:~/voice-recognition/

# 9. Run the API server (background)
nohup uvicorn cloud_api:app --host 0.0.0.0 --port 8000 &

# 10. Test it
curl http://YOUR_VM_IP:8000/
# → {"status": "online", "service": "Speaker Recognition API"}
```

---

## Option 2 (Easiest): Hugging Face Spaces

No SSH, no Linux config — just push code via web UI.

```
1. Go to https://huggingface.co/spaces
2. Create New Space → SDK: Docker
3. Upload all your .py files + speaker_profiles/ folder
4. Create a Dockerfile:
```

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt fastapi uvicorn python-multipart
COPY . .
CMD ["uvicorn", "cloud_api:app", "--host", "0.0.0.0", "--port", "7860"]
```

```
5. Hugging Face gives you a public URL automatically:
   https://YOUR_USERNAME-voice-api.hf.space/identify
```

---

## IoT Client Code

### Raspberry Pi (Python)

```python
import requests

SERVER = "http://YOUR_SERVER_IP:8000"

def verify_at_cloud(audio_path: str, claimed_identity: str) -> bool:
    with open(audio_path, "rb") as f:
        response = requests.post(
            f"{SERVER}/verify",
            files={"audio": ("audio.wav", f, "audio/wav")},
            data={"claimed_identity": claimed_identity, "threshold": 0.30},
            timeout=10,
        )
    result = response.json()
    print(f"Score: {result['score']} — {result['action']}")
    return result["accepted"]

# Use it:
if verify_at_cloud("recorded.wav", "Omar"):
    # GPIO.output(RELAY_PIN, GPIO.HIGH)  # unlock
    print("Door unlocked")
else:
    print("Access denied")
```

### ESP32 (MicroPython) — Minimal

```python
import urequests
import machine

SERVER = "http://YOUR_SERVER_IP:8000"
RELAY_PIN = machine.Pin(25, machine.Pin.OUT)

def verify(audio_bytes, name):
    boundary = "----FormBound"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="claimed_identity"\r\n\r\n{name}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="audio.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode() + audio_bytes + f"\r\n--{boundary}--\r\n".encode()

    r = urequests.post(
        SERVER + "/verify",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        data=body
    )
    accepted = r.json()["accepted"]
    r.close()
    return accepted

# In your main loop:
# audio_bytes = record_i2s_microphone()
# if verify(audio_bytes, "Omar"):
#     RELAY_PIN.value(1)  # unlock door for 3 seconds
```

---

## Protocol Choice

| Protocol | Use When | Notes |
|---|---|---|
| **HTTP REST** | One-shot: "verify this clip" | Simplest. ESP32 compatible. |
| **WebSocket** | Real-time: continuous speaker monitoring | Needs more RAM on device |
| **MQTT** | Telemetry: log events, publish results to dashboard | Add HiveMQ free broker |

### Adding MQTT for Event Logging (Optional)

```python
# On the server side — publish result to MQTT after each verification
import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"  # free public broker
TOPIC = "voicelock/events"

def publish_event(accepted: bool, speaker: str, score: float):
    client = mqtt.Client()
    client.connect(BROKER, 1883)
    payload = json.dumps({"accepted": accepted, "speaker": speaker, "score": score})
    client.publish(TOPIC, payload)
    client.disconnect()
```

Subscribe on any device (phone, laptop) to see real-time lock events:
```bash
mosquitto_sub -h broker.hivemq.com -t "voicelock/events"
```

---

## Cost Estimate

| Component | Provider | Monthly Cost |
|---|---|---|
| Cloud inference server | Oracle Cloud Always Free | **$0** |
| MQTT broker | HiveMQ Cloud Free (10 connections) | **$0** |
| Domain / HTTPS | Cloudflare (free SSL via nginx) | **$0** |
| IoT hardware | ESP32 + I2S mic + relay | ~₹700 one-time |
| **Total ongoing** | | **$0/month** |
