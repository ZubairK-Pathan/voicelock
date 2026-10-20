
import os
import re
import json
import pickle
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import torch

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)



PROJECT_ROOT = Path(__file__).resolve().parent
DATASET_DIR = PROJECT_ROOT / "dataset"
PROCESSED_DIR = PROJECT_ROOT / "processed_dataset"
PROFILES_DIR = PROJECT_ROOT / "speaker_profiles"
RESULTS_DIR = PROJECT_ROOT / "results"

SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wma", ".webm"}
SOUNDFILE_EXTENSIONS = {".wav", ".flac", ".ogg"}
TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1  # mono

PROFILES_FILE = PROFILES_DIR / "profiles.pkl"
EMBEDDINGS_FILE = PROFILES_DIR / "all_embeddings.pkl"
SPLIT_INFO_FILE = PROFILES_DIR / "split_info.json"

FILENAME_PATTERN = re.compile(
    r"^(?P<prefix>[A-Za-z]+)_S(?P<sentence>\d+)_R(?P<repetition>\d+)$",
    re.IGNORECASE,
)




def _find_ffmpeg() -> str:
    """Find ffmpeg executable."""
    path = shutil.which("ffmpeg")
    if path is None:
        raise RuntimeError(
            "ffmpeg not found. Install it with: brew install ffmpeg"
        )
    return path


def _find_ffprobe() -> str:
    """Find ffprobe executable."""
    path = shutil.which("ffprobe")
    if path is None:
        raise RuntimeError(
            "ffprobe not found. Install ffmpeg with: brew install ffmpeg"
        )
    return path


def _ffprobe_info(filepath: Path) -> Optional[dict]:
    """
    Get audio metadata using ffprobe (works for all formats including M4A, MP3).
    Returns dict with sample_rate, channels, duration_seconds, format.
    """
    try:
        ffprobe = _find_ffprobe()
        result = subprocess.run(
            [
                ffprobe,
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                "-show_format",
                str(filepath),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None

        import json as _json
        data = _json.loads(result.stdout)

        # Find the audio stream
        audio_stream = None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                audio_stream = stream
                break

        if audio_stream is None:
            return None

        sample_rate = int(audio_stream.get("sample_rate", 0))
        channels = int(audio_stream.get("channels", 0))

        # Duration: prefer stream duration, fallback to format duration
        duration = float(audio_stream.get("duration", 0))
        if duration == 0:
            duration = float(data.get("format", {}).get("duration", 0))

        return {
            "sample_rate": sample_rate,
            "channels": channels,
            "duration_seconds": round(duration, 2),
            "format": filepath.suffix.lower(),
            "readable": True,
        }
    except Exception as e:
        return {
            "readable": False,
            "error": str(e),
            "format": filepath.suffix.lower(),
        }


def _ffmpeg_to_wav(input_path: Path, output_path: Path, sr: int = TARGET_SAMPLE_RATE, channels: int = 1):
    """
    Convert any audio file to WAV using ffmpeg.
    """
    ffmpeg = _find_ffmpeg()
    result = subprocess.run(
        [
            ffmpeg,
            "-y",                    # overwrite
            "-i", str(input_path),   # input
            "-ar", str(sr),          # sample rate
            "-ac", str(channels),    # channels
            "-f", "wav",             # output format
            str(output_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg conversion failed for {input_path}:\n{result.stderr}"
        )


# ─── File Discovery ──────────────────────────────────────────────────────────


def get_speaker_dirs(dataset_dir: Path = DATASET_DIR) -> list[Path]:
    """Return sorted list of speaker directories in the dataset folder."""
    if not dataset_dir.exists():
        return []
    return sorted(
        [d for d in dataset_dir.iterdir() if d.is_dir() and not d.name.startswith(".")],
        key=lambda d: d.name,
    )


def get_audio_files(speaker_dir: Path) -> list[Path]:
    """Return sorted list of audio files in a speaker directory."""
    return sorted(
        [
            f
            for f in speaker_dir.iterdir()
            if f.is_file()
            and f.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
            and not f.name.startswith(".")
        ],
        key=lambda f: f.name,
    )


# ─── Filename Parsing ────────────────────────────────────────────────────────


def parse_filename(filepath: Path) -> Optional[dict]:
    """
    Parse a recording filename to extract metadata.

    Returns dict with keys: prefix, sentence, repetition, speaker (from parent dir)
    Returns None if the filename doesn't match the expected pattern.
    """
    stem = filepath.stem
    match = FILENAME_PATTERN.match(stem)
    if not match:
        return None
    return {
        "prefix": match.group("prefix"),
        "sentence": int(match.group("sentence")),
        "repetition": int(match.group("repetition")),
        "speaker": filepath.parent.name,
    }


# ─── Audio Metadata ──────────────────────────────────────────────────────────


def get_audio_info(filepath: Path) -> Optional[dict]:
    """
    Get audio file metadata (duration, sample rate, channels).

    Uses soundfile for WAV/FLAC/OGG, ffprobe for everything else.
    """
    ext = filepath.suffix.lower()

    # Try soundfile first for formats it supports
    if ext in SOUNDFILE_EXTENSIONS:
        try:
            info = sf.info(str(filepath))
            return {
                "sample_rate": info.samplerate,
                "channels": info.channels,
                "duration_seconds": round(info.duration, 2),
                "num_frames": info.frames,
                "format": ext,
                "readable": True,
            }
        except Exception:
            pass

    # Use ffprobe for M4A, MP3, or as fallback
    return _ffprobe_info(filepath)




def load_audio(filepath: Path, target_sr: int = TARGET_SAMPLE_RATE) -> tuple[torch.Tensor, int]:
    """
    Load an audio file and convert to mono at the target sample rate.

    Uses soundfile for WAV/FLAC/OGG. For M4A/MP3/other formats, converts
    to WAV via ffmpeg first, then loads with soundfile.

    Returns (waveform, sample_rate) where waveform is shape (1, num_samples).
    """
    ext = filepath.suffix.lower()
    temp_wav = None

    try:
        if ext in SOUNDFILE_EXTENSIONS:
            # Direct load
            data, sr = sf.read(str(filepath), dtype="float32")
        else:
            # Convert via ffmpeg to a temp WAV file
            temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_wav.close()
            _ffmpeg_to_wav(filepath, Path(temp_wav.name), sr=target_sr, channels=1)
            data, sr = sf.read(temp_wav.name, dtype="float32")

        # Convert to torch tensor
        if data.ndim == 1:
            waveform = torch.tensor(data, dtype=torch.float32).unsqueeze(0)
        else:
            # Multi-channel: average to mono
            waveform = torch.tensor(data.mean(axis=1), dtype=torch.float32).unsqueeze(0)

        # Resample if needed (only when we didn't already set target_sr via ffmpeg)
        if sr != target_sr:
            import torchaudio
            resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=target_sr)
            waveform = resampler(waveform)
            sr = target_sr

        return waveform, sr

    finally:
        # Clean up temp file
        if temp_wav is not None:
            try:
                os.unlink(temp_wav.name)
            except OSError:
                pass


def normalize_audio(waveform: torch.Tensor) -> torch.Tensor:
    """Peak-normalize audio waveform to [-1, 1]."""
    max_val = waveform.abs().max()
    if max_val > 0:
        waveform = waveform / max_val
    return waveform


def preprocess_audio(filepath: Path) -> tuple[torch.Tensor, int]:
    """Full preprocessing pipeline: load → mono → resample → normalize."""
    waveform, sr = load_audio(filepath, target_sr=TARGET_SAMPLE_RATE)
    waveform = normalize_audio(waveform)
    return waveform, sr


def save_wav(waveform: torch.Tensor, filepath: Path, sample_rate: int = TARGET_SAMPLE_RATE):
    """Save waveform as WAV file using soundfile."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    # Convert from (1, N) or (C, N) to (N,) or (N, C) for soundfile
    data = waveform.squeeze(0).numpy()
    sf.write(str(filepath), data, sample_rate)


# ─── Speaker Embeddings ──────────────────────────────────────────────────────


def get_device() -> torch.device:
    """Select the best available device: MPS (Apple Silicon) > CPU."""
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        try:
            # Test that MPS actually works (some ops may not be supported)
            test = torch.zeros(1, device="mps")
            del test
            return torch.device("mps")
        except Exception:
            pass
    return torch.device("cpu")


def load_embedding_model(device: Optional[torch.device] = None):
    """
    Load the pretrained ECAPA-TDNN speaker embedding model from SpeechBrain.

    Returns the classifier object that can generate embeddings.

    Note: SpeechBrain 1.1.0 doesn't support MPS device_type, so we force CPU.
    The ECAPA-TDNN model is small (~7M params) and runs fast on CPU.
    """
    from speechbrain.inference.speaker import EncoderClassifier

    # Force CPU — SpeechBrain 1.1.0 crashes on MPS because it only
    # handles device_type for "cpu" and "cuda", not "mps".
    # CPU is fast enough for this small model.
    run_device = "cpu"

    # SpeechBrain downloads model to a local cache
    model_save_dir = PROJECT_ROOT / ".model_cache"
    model_save_dir.mkdir(exist_ok=True)

    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(model_save_dir),
        run_opts={"device": run_device},
    )
    return classifier


def generate_embedding(
    classifier, waveform: torch.Tensor, sample_rate: int = TARGET_SAMPLE_RATE
) -> np.ndarray:
    """
    Generate a speaker embedding from a preprocessed waveform.

    Args:
        classifier: SpeechBrain EncoderClassifier
        waveform: Tensor of shape (1, num_samples)
        sample_rate: Sample rate of the waveform

    Returns:
        numpy array of shape (embedding_dim,) — typically 192 for ECAPA-TDNN
    """
    with torch.no_grad():
        embedding = classifier.encode_batch(waveform)
    return embedding.squeeze().cpu().numpy()




def load_profiles() -> dict:
    """Load saved speaker profiles from disk."""
    if not PROFILES_FILE.exists():
        raise FileNotFoundError(
            f"Speaker profiles not found at {PROFILES_FILE}.\n"
            "Run 'python build_profiles.py' first."
        )
    with open(PROFILES_FILE, "rb") as f:
        return pickle.load(f)


def load_embeddings() -> dict:
    """Load all saved embeddings with metadata from disk."""
    if not EMBEDDINGS_FILE.exists():
        raise FileNotFoundError(
            f"Embeddings not found at {EMBEDDINGS_FILE}.\n"
            "Run 'python build_profiles.py' first."
        )
    with open(EMBEDDINGS_FILE, "rb") as f:
        return pickle.load(f)


def load_split_info() -> dict:
    """Load train/test split information from disk."""
    if not SPLIT_INFO_FILE.exists():
        raise FileNotFoundError(
            f"Split info not found at {SPLIT_INFO_FILE}.\n"
            "Run 'python build_profiles.py' first."
        )
    with open(SPLIT_INFO_FILE, "r") as f:
        return json.load(f)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def register_speaker(
    name: str,
    audio_paths: list,
    classifier,
    existing_profiles: dict,
) -> dict:
    """
    Register a new speaker from a list of audio recordings.

    Saves raw files to dataset/<name>/, preprocessed files to processed_dataset/<name>/,
    computes ECAPA-TDNN embeddings for each, averages them into one profile vector,
    and persists the updated profiles.pkl atomically to disk.

    Args:
        name: Speaker's name (used as folder name and profile key).
        audio_paths: List of Path objects pointing to raw audio recordings.
        classifier: Pre-loaded ECAPA-TDNN classifier.
        existing_profiles: Currently loaded profiles dict — updated in-place and returned.

    Returns:
        Updated profiles dict including the new speaker.

    Raises:
        ValueError: If name is empty, already registered, or fewer than 3 audio paths given.
    """
    name = name.strip()
    if not name:
        raise ValueError("Speaker name cannot be empty.")
    if name in existing_profiles:
        raise ValueError(f"Speaker '{name}' is already registered.")
    if len(audio_paths) < 3:
        raise ValueError(f"Need at least 3 recordings, got {len(audio_paths)}.")

    raw_dir = DATASET_DIR / name
    raw_dir.mkdir(parents=True, exist_ok=True)
    proc_dir = PROCESSED_DIR / name
    proc_dir.mkdir(parents=True, exist_ok=True)

    embeddings = []
    for idx, src_path in enumerate(audio_paths, start=1):
        src_path = Path(src_path)
        raw_dest = raw_dir / f"{name}_Enrollment_R{idx:02d}{src_path.suffix}"
        shutil.copy2(src_path, raw_dest)

        waveform, sr = load_audio(src_path, target_sr=TARGET_SAMPLE_RATE)
        waveform = normalize_audio(waveform)
        proc_dest = proc_dir / f"{name}_Enrollment_R{idx:02d}.wav"
        save_wav(waveform, proc_dest, sample_rate=sr)

        emb = generate_embedding(classifier, waveform, sr)
        embeddings.append(emb)

    profile_embedding = np.mean(embeddings, axis=0)
    existing_profiles[name] = profile_embedding

    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PROFILES_FILE.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(existing_profiles, f)
    tmp.replace(PROFILES_FILE)

    return existing_profiles


def delete_speaker(name: str, existing_profiles: dict) -> dict:
    """
    Remove a registered speaker from the in-memory profiles and persist the change.

    Raw/processed audio files on disk are kept (not deleted).

    Args:
        name: Name of the speaker to remove.
        existing_profiles: Currently loaded profiles dict.

    Returns:
        Updated profiles dict with the speaker removed.

    Raises:
        ValueError: If speaker is not found.
    """
    if name not in existing_profiles:
        raise ValueError(f"Speaker '{name}' not found in profiles.")

    del existing_profiles[name]

    tmp = PROFILES_FILE.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(existing_profiles, f)
    tmp.replace(PROFILES_FILE)

    return existing_profiles

