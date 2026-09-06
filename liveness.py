#!/usr/bin/env python3
"""
liveness.py — Digits-based Challenge-Response Liveness Detection.

Defends against replay attacks by requiring the user to speak a randomly
generated 3-digit sequence displayed on screen. A pre-recorded voice clip
cannot know what digits to say, so it will fail.

Pipeline:
    1. generate_challenge()  → e.g. ["7", "2", "9"]
    2. User sees "Say: 7  2  9" on screen and records audio
    3. transcribe_audio(audio_path) → "seven two nine"
    4. verify_liveness(transcript, challenge) → True / False

Dependencies:
    pip install vosk
    The Vosk small English model (~40MB) is downloaded automatically on first run
    to .model_cache/vosk-model-small-en/

Uses the small English model — fast, offline, no API key required.
"""

import json
import random
import struct
import wave
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

DIGIT_WORDS = {
    "0": ["zero", "oh"],
    "1": ["one"],
    "2": ["two"],
    "3": ["three"],
    "4": ["four"],
    "5": ["five"],
    "6": ["six"],
    "7": ["seven"],
    "8": ["eight"],
    "9": ["nine"],
}

WORD_TO_DIGIT = {}
for digit, words in DIGIT_WORDS.items():
    for word in words:
        WORD_TO_DIGIT[word] = digit

MODEL_DIR = Path(__file__).resolve().parent / ".model_cache" / "vosk-model-small-en-us"
MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
MODEL_ZIP = Path(__file__).resolve().parent / ".model_cache" / "vosk-model-small-en-us-0.15.zip"

_vosk_model = None


def _ensure_model() -> Path:
    """Download the Vosk small English model if not already present."""
    if MODEL_DIR.exists():
        return MODEL_DIR

    MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading Vosk model (~40MB) to {MODEL_DIR.parent}...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_ZIP)

    print("Extracting...")
    with zipfile.ZipFile(MODEL_ZIP, "r") as zf:
        zf.extractall(MODEL_DIR.parent)

    extracted = list(MODEL_DIR.parent.glob("vosk-model-small-en-us*"))
    if extracted and not MODEL_DIR.exists():
        extracted[0].rename(MODEL_DIR)

    MODEL_ZIP.unlink(missing_ok=True)
    print("Vosk model ready.")
    return MODEL_DIR


def _get_model():
    """Return a cached Vosk model instance."""
    global _vosk_model
    if _vosk_model is None:
        from vosk import Model
        model_path = _ensure_model()
        _vosk_model = Model(str(model_path))
    return _vosk_model


def generate_challenge(length: int = 3) -> list[str]:
    """
    Generate a random digit challenge sequence.

    Args:
        length: Number of digits in the challenge (3 or 4 recommended).

    Returns:
        List of digit strings, e.g. ["7", "2", "9"]
    """
    return [str(random.randint(0, 9)) for _ in range(length)]


def challenge_display(challenge: list[str]) -> str:
    """
    Format the challenge for on-screen display.

    Returns a wide-spaced string like "7   2   9".
    """
    return "   ".join(challenge)


def challenge_expected_words(challenge: list[str]) -> list[str]:
    """
    Convert digit list to expected spoken word list.

    e.g. ["7", "2", "9"] → ["seven", "two", "nine"]
    """
    return [DIGIT_WORDS[d][0] for d in challenge]


def transcribe_audio(audio_path: str) -> Optional[str]:
    """
    Transcribe a WAV audio file to text using Vosk (offline STT).

    Always converts input to 16kHz mono PCM16 WAV via ffmpeg before
    passing to Vosk, regardless of input format. This handles Streamlit's
    audio_input which may return OGG/WebM internally even with a .wav suffix.

    Args:
        audio_path: Path to any audio file.

    Returns:
        Lowercase transcription string, or None if transcription failed.
    """
    from vosk import KaldiRecognizer
    import subprocess
    import tempfile
    import os

    audio_path = Path(audio_path)
    tmp_wav = None

    try:
        # Always force-convert to 16kHz mono signed-16bit PCM WAV.
        # Vosk is strict: wrong sample rate or encoding causes silent hangs.
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        tmp_wav = Path(tmp.name)

        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(audio_path),
                "-ar", "16000",      # 16kHz sample rate (Vosk requirement)
                "-ac", "1",          # mono
                "-sample_fmt", "s16",  # signed 16-bit PCM
                "-f", "wav",
                str(tmp_wav),
            ],
            capture_output=True,
            timeout=15,
        )
        if result.returncode != 0:
            print(f"ffmpeg error: {result.stderr.decode()}")
            return None

        model = _get_model()
        rec = KaldiRecognizer(model, 16000)
        rec.SetWords(True)

        transcript_parts = []
        with wave.open(str(tmp_wav), "rb") as wf:
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                if rec.AcceptWaveform(data):
                    result_json = json.loads(rec.Result())
                    transcript_parts.append(result_json.get("text", ""))

        final = json.loads(rec.FinalResult())
        transcript_parts.append(final.get("text", ""))
        full_transcript = " ".join(p for p in transcript_parts if p).strip().lower()
        return full_transcript if full_transcript else ""

    except subprocess.TimeoutExpired:
        print("ffmpeg conversion timed out")
        return None
    except Exception as e:
        print(f"Transcription error: {e}")
        return None
    finally:
        if tmp_wav and tmp_wav.exists():
            try:
                os.unlink(tmp_wav)
            except OSError:
                pass



def verify_liveness(transcript: Optional[str], challenge: list[str]) -> tuple[bool, str]:
    """
    Check whether the spoken transcript matches the digit challenge.

    Uses word-to-digit mapping so "seven two nine" matches ["7", "2", "9"].
    Requires ALL digits to be present in order — partial matches are rejected.

    Args:
        transcript: Lowercase transcription from transcribe_audio().
        challenge: The challenge digit list from generate_challenge().

    Returns:
        (is_live, reason_message) tuple.
        is_live is True only if all digits were spoken correctly in order.
    """
    if transcript is None:
        return False, "Could not transcribe audio. Please speak clearly."

    if not transcript.strip():
        return False, "No speech detected. Please try again."

    words = transcript.lower().split()
    spoken_digits = []
    for word in words:
        clean = word.strip(".,!?")
        if clean in WORD_TO_DIGIT:
            spoken_digits.append(WORD_TO_DIGIT[clean])
        elif clean.isdigit() and clean in DIGIT_WORDS:
            spoken_digits.append(clean)

    expected = challenge
    if spoken_digits == expected:
        return True, f"Liveness verified. Heard: {' '.join(spoken_digits)}"

    if len(spoken_digits) == 0:
        return False, f"No digits heard in transcript: '{transcript}'"

    return False, (
        f"Challenge failed. Expected {' '.join(expected)}, "
        f"heard {' '.join(spoken_digits) if spoken_digits else 'nothing'}."
    )


def run_liveness_check(audio_path: str, challenge: list[str]) -> tuple[bool, str, Optional[str]]:
    """
    Full liveness pipeline: transcribe audio and verify against challenge.

    Args:
        audio_path: Path to the spoken audio file.
        challenge: The digit list that was shown to the user.

    Returns:
        (is_live, reason_message, transcript) — all three for debugging/logging.
    """
    transcript = transcribe_audio(audio_path)
    is_live, reason = verify_liveness(transcript, challenge)
    return is_live, reason, transcript


if __name__ == "__main__":
    import sys

    challenge = generate_challenge(3)
    print(f"\nChallenge: {challenge_display(challenge)}")
    print(f"Expected words: {challenge_expected_words(challenge)}")

    if len(sys.argv) > 1:
        audio_file = sys.argv[1]
        print(f"\nTranscribing: {audio_file}")
        is_live, reason, transcript = run_liveness_check(audio_file, challenge)
        print(f"Transcript : {transcript}")
        print(f"Liveness   : {'PASS' if is_live else 'FAIL'}")
        print(f"Reason     : {reason}")
    else:
        print("Usage: python liveness.py path/to/audio.wav")
        print("(Challenge is printed above — speak it and pass the file path)")
