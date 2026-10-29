#!/usr/bin/env python3
"""
scripts/warmup_models.py — Container Pre-Warm and Model Cache Initializer.

Downloads and validates both the SpeechBrain ECAPA-TDNN speaker embedding model
and the Vosk small English STT model during container image build.
Ensures the resulting container image is self-contained with zero runtime
model download dependencies.
"""

from pathlib import Path
import sys

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from audio_utils import load_embedding_model
from liveness import _ensure_model


def warmup_all_models() -> bool:
    """Download and initialize both production models."""
    print("[VoiceLock Build] Pre-warming SpeechBrain ECAPA-TDNN embedding model...")
    classifier = load_embedding_model()
    if classifier is None:
        raise RuntimeError("Failed to initialize SpeechBrain ECAPA-TDNN model.")
    print("[VoiceLock Build] SpeechBrain model initialized successfully.")

    print("[VoiceLock Build] Pre-warming Vosk STT liveness model...")
    from vosk import Model
    vosk_path = _ensure_model()
    if not vosk_path or not Path(vosk_path).exists():
        raise RuntimeError("Failed to initialize Vosk STT model.")
    
    # Strictly instantiate the Vosk C++ Model to verify all weights and graphs are functional
    try:
        vosk_model = Model(str(vosk_path))
        if vosk_model is None:
            raise RuntimeError("Vosk Model returned None.")
    except Exception as exc:
        raise RuntimeError(f"Vosk Model initialization failed for path '{vosk_path}': {exc}") from exc

    print(f"[VoiceLock Build] Vosk STT model verified and instantiated successfully from {vosk_path}.")

    print("[VoiceLock Build] All production biometric and STT models ready.")
    return True


if __name__ == "__main__":
    warmup_all_models()
