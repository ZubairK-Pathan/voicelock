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

import enum
import json
import secrets
import struct
import threading
import time
import urllib.request
import wave
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

DIGIT_WORDS = {
    "0": ["zero", "oh", "o"],
    "1": ["one", "won"],
    "2": ["two", "to", "too"],
    "3": ["three"],
    "4": ["four", "for", "fore"],
    "5": ["five"],
    "6": ["six"],
    "7": ["seven"],
    "8": ["eight", "ate"],
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


# ─── Challenge Data Structures & Storage Interface ───────────────────────────

class ChallengeStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


@dataclass
class LivenessChallenge:
    """
    Representation of an active or consumed biometric liveness challenge.
    
    Attributes:
        challenge_id: Cryptographically unpredictable unique identifier.
        session_id: Client verification session to which the challenge is bound.
        digits: The random sequence of digits the user must speak.
        created_at: Epoch timestamp of challenge generation.
        expires_at: Epoch timestamp when the challenge expires.
        claimed_identity: Optional claimed speaker name bound to this challenge.
        status: Current lifecycle status (PENDING, CONSUMED, EXPIRED).
    """
    challenge_id: str
    session_id: str
    digits: list[str]
    created_at: float
    expires_at: float
    claimed_identity: Optional[str] = None
    status: ChallengeStatus = ChallengeStatus.PENDING

    @property
    def is_pending(self) -> bool:
        return self.status == ChallengeStatus.PENDING

    @property
    def display_text(self) -> str:
        return "   ".join(self.digits)

    def is_expired(self, current_time: float) -> bool:
        return current_time > self.expires_at


class BaseChallengeStore(ABC):
    """
    Abstract interface for managing the liveness challenge lifecycle.
    Decouples storage from API logic, allowing in-memory prototypes to be replaced
    with distributed stores (e.g., Redis or PostgreSQL challenge tables) in production.
    """

    @abstractmethod
    def create_challenge(
        self,
        session_id: Optional[str] = None,
        claimed_identity: Optional[str] = None,
        ttl_seconds: int = 60,
        length: int = 3,
    ) -> LivenessChallenge:
        """Generate and store a new challenge bound to a session."""
        pass

    @abstractmethod
    def get_challenge(self, challenge_id: str) -> Optional[LivenessChallenge]:
        """Retrieve a challenge by ID without mutating its lifecycle status."""
        pass

    @abstractmethod
    def validate_and_consume(
        self,
        challenge_id: str,
        session_id: str,
        claimed_identity: Optional[str] = None,
    ) -> tuple[bool, str, Optional[LivenessChallenge]]:
        """
        Atomically validate and consume a challenge.
        Enforces single-attempt invalidation ('burn-on-use'): if the challenge is
        pending, not expired, and matches session and identity, it is immediately
        marked CONSUMED under a concurrency lock.
        
        Returns:
            (success, failure_reason, challenge_object)
        """
        pass

    @abstractmethod
    def cleanup_expired(self) -> int:
        """Purge expired and consumed challenges; returns count of removed items."""
        pass


class InMemoryChallengeStore(BaseChallengeStore):
    """
    Thread-safe in-memory challenge store for single-process development.

    Architectural Limitations & Production Considerations:
    1. Scope: State is local to the current Python process.
    2. Multi-Worker / Distributed Incompatibility: If Uvicorn runs with multiple
       workers (`--workers > 1`) or if multiple server instances run behind a
       load balancer, in-memory challenge state will not be shared across processes.
    3. Production Target: In multi-worker production deployments, replace this
       implementation with a distributed Redis or PostgreSQL challenge store
       conforming to BaseChallengeStore.
    """

    def __init__(self, time_func: Callable[[], float] = time.time):
        self._challenges: dict[str, LivenessChallenge] = {}
        self._lock = threading.Lock()
        self._time_func = time_func

    def create_challenge(
        self,
        session_id: Optional[str] = None,
        claimed_identity: Optional[str] = None,
        ttl_seconds: int = 60,
        length: int = 3,
    ) -> LivenessChallenge:
        digits = generate_challenge(length)
        challenge_id = f"ch_{secrets.token_hex(16)}"
        clean_session = str(session_id).strip() if session_id else f"sess_{secrets.token_hex(16)}"
        clean_claimed = str(claimed_identity).strip() if claimed_identity else None

        now = self._time_func()
        challenge = LivenessChallenge(
            challenge_id=challenge_id,
            session_id=clean_session,
            digits=digits,
            created_at=now,
            expires_at=now + ttl_seconds,
            claimed_identity=clean_claimed,
            status=ChallengeStatus.PENDING,
        )

        with self._lock:
            self._challenges[challenge_id] = challenge

        return challenge

    def get_challenge(self, challenge_id: str) -> Optional[LivenessChallenge]:
        with self._lock:
            return self._challenges.get(challenge_id)

    def validate_and_consume(
        self,
        challenge_id: str,
        session_id: str,
        claimed_identity: Optional[str] = None,
    ) -> tuple[bool, str, Optional[LivenessChallenge]]:
        """
        Atomically inspect and consume the challenge.
        Applies Single-Attempt Invalidation: any valid PENDING challenge is marked
        CONSUMED immediately to prevent replay and race conditions.
        """
        now = self._time_func()
        with self._lock:
            challenge = self._challenges.get(challenge_id)
            if challenge is None:
                return False, "Invalid or unknown challenge ID.", None

            if challenge.status == ChallengeStatus.CONSUMED:
                return False, "Challenge has already been consumed or invalidated.", None

            if challenge.is_expired(now) or challenge.status == ChallengeStatus.EXPIRED:
                challenge.status = ChallengeStatus.EXPIRED
                return False, "Challenge has expired.", None

            if challenge.session_id != str(session_id).strip():
                return False, "Session mismatch for this challenge.", None

            if challenge.claimed_identity is not None:
                clean_claimed = str(claimed_identity).strip() if claimed_identity else ""
                if challenge.claimed_identity != clean_claimed:
                    return False, f"Challenge is bound to speaker '{challenge.claimed_identity}', not '{clean_claimed}'.", None

            # Atomically burn on use
            challenge.status = ChallengeStatus.CONSUMED
            return True, "Challenge successfully validated and consumed.", challenge

    def cleanup_expired(self) -> int:
        now = self._time_func()
        with self._lock:
            to_remove = [
                cid for cid, ch in self._challenges.items()
                if ch.is_expired(now) or ch.status in (ChallengeStatus.EXPIRED, ChallengeStatus.CONSUMED)
            ]
            for cid in to_remove:
                del self._challenges[cid]
            return len(to_remove)


default_challenge_store = InMemoryChallengeStore()


# ─── Digit Generation & Presentation Utilities ────────────────────────────────

def generate_challenge(length: int = 3) -> list[str]:
    """
    Generate a random digit challenge sequence using secrets.randbelow (CSPRNG).
    Avoids pseudo-random generators (random.randint) to prevent replay/prediction.

    Args:
        length: Number of digits in the challenge (3 recommended for spoken ease).

    Returns:
        List of digit strings, e.g. ["7", "2", "9"]
    """
    return [str(secrets.randbelow(10)) for _ in range(length)]


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
        grammar = json.dumps(list(WORD_TO_DIGIT.keys()) + [str(i) for i in range(10)] + ["[unk]"])
        try:
            rec = KaldiRecognizer(model, 16000, grammar)
        except Exception:
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
        elif clean.isdigit():
            for d in clean:
                if d in DIGIT_WORDS:
                    spoken_digits.append(d)

    expected = challenge
    if spoken_digits == expected:
        return True, "Liveness verified successfully."

    if len(spoken_digits) == 0:
        return False, "No digits heard in audio recording."

    return False, "Challenge failed: spoken digits did not match the required challenge sequence."


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
