#!/usr/bin/env python3

import sys
import time
from pathlib import Path

from audio_utils import (
    DATASET_DIR,
    PROCESSED_DIR,
    TARGET_SAMPLE_RATE,
    get_speaker_dirs,
    get_audio_files,
    preprocess_audio,
    save_wav,
)

def preprocess_dataset(
    dataset_dir: Path = DATASET_DIR,
    output_dir: Path = PROCESSED_DIR,
):
    """Preprocess all audio files in the dataset."""

    print("=" * 60)
    print("  AUDIO PREPROCESSING")
    print("=" * 60)
    print(f"\nSource:      {dataset_dir}")
    print(f"Destination: {output_dir}")
    print(f"Target:      {TARGET_SAMPLE_RATE}Hz, mono, WAV, normalized")
    print()

    speaker_dirs = get_speaker_dirs(dataset_dir)
    if not speaker_dirs:
        print("✗ No speaker directories found.")
        sys.exit(1)

    total_processed = 0
    total_skipped = 0
    total_errors = 0
    start_time = time.time()

    for speaker_dir in speaker_dirs:
        speaker_name = speaker_dir.name
        audio_files = get_audio_files(speaker_dir)
        speaker_output_dir = output_dir / speaker_name

        print(f"Processing {speaker_name} ({len(audio_files)} files)...")

        for audio_file in audio_files:
            output_file = speaker_output_dir / f"{audio_file.stem}.wav"

            if output_file.exists():
                total_skipped += 1
                continue

            try:
                waveform, sr = preprocess_audio(audio_file)
                save_wav(waveform, output_file, sr)
                total_processed += 1
                print(f"  ✓ {audio_file.name} → {output_file.name}")
            except Exception as e:
                total_errors += 1
                print(f"  ✗ {audio_file.name} — Error: {e}")

    elapsed = time.time() - start_time

    print()
    print("=" * 60)
    print("  PREPROCESSING SUMMARY")
    print("=" * 60)
    print(f"  Processed: {total_processed}")
    print(f"  Skipped:   {total_skipped} (already exist)")
    print(f"  Errors:    {total_errors}")
    print(f"  Time:      {elapsed:.1f}s")
    print()

    if total_errors > 0:
        print("  ⚠ Some files failed to process. Check errors above.")
    else:
        print("  ✓ All files preprocessed successfully.")

    print()
    print("  Output contents:")
    for speaker_dir in get_speaker_dirs(output_dir):
        wav_files = list(speaker_dir.glob("*.wav"))
        print(f"    {speaker_dir.name}: {len(wav_files)} WAV files")

    print()


if __name__ == "__main__":
    preprocess_dataset()
