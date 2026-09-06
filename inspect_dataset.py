#!/usr/bin/env python3

import sys
from collections import defaultdict
from pathlib import Path

from audio_utils import (
    DATASET_DIR,
    get_speaker_dirs,
    get_audio_files,
    get_audio_info,
    parse_filename,
)


def inspect_dataset(dataset_dir: Path = DATASET_DIR):
    """Inspect the dataset directory and print a comprehensive summary."""

    print("=" * 60)
    print("  DATASET INSPECTION")
    print("=" * 60)
    print(f"\nDataset directory: {dataset_dir}")

    if not dataset_dir.exists():
        print(f"\n✗ Dataset directory does not exist: {dataset_dir}")
        print("  Please create it and add speaker recordings.")
        sys.exit(1)

    speaker_dirs = get_speaker_dirs(dataset_dir)

    if not speaker_dirs:
        print("\n✗ No speaker folders found in the dataset directory.")
        sys.exit(1)

    print(f"Speakers detected: {len(speaker_dirs)}")
    print()

    total_files = 0
    total_duration = 0.0
    total_corrupted = 0
    all_formats = defaultdict(int)
    all_sample_rates = set()
    all_channels = set()
    warnings_list = []

    for speaker_dir in speaker_dirs:
        speaker_name = speaker_dir.name
        audio_files = get_audio_files(speaker_dir)

        print("-" * 60)
        print(f"  Speaker: {speaker_name}")
        print("-" * 60)

        if not audio_files:
            print("  ✗ No audio files found!\n")
            warnings_list.append(f"Speaker '{speaker_name}' has no audio files.")
            continue

        # Analyze files
        formats = defaultdict(int)
        durations = []
        sample_rates = set()
        channels = set()
        sentences = set()
        corrupted = []
        parsed_count = 0

        for f in audio_files:
            info = get_audio_info(f)
            fmt = f.suffix.lower()
            formats[fmt] += 1
            all_formats[fmt] += 1

            if info and info.get("readable"):
                durations.append(info["duration_seconds"])
                sample_rates.add(info["sample_rate"])
                channels.add(info["channels"])
                all_sample_rates.add(info["sample_rate"])
                all_channels.add(info["channels"])
            else:
                corrupted.append(f.name)
                error_msg = info.get("error", "Unknown error") if info else "Unknown error"
                warnings_list.append(
                    f"Corrupted/unreadable: {speaker_name}/{f.name} — {error_msg}"
                )

            # Parse filename
            parsed = parse_filename(f)
            if parsed:
                sentences.add(parsed["sentence"])
                parsed_count += 1

        total_files += len(audio_files)
        total_duration += sum(durations)
        total_corrupted += len(corrupted)

        # Print speaker summary
        print(f"  Files:        {len(audio_files)}")
        print(f"  Formats:      {', '.join(f'{ext} ({cnt})' for ext, cnt in sorted(formats.items()))}")

        if durations:
            print(f"  Total dur:    {sum(durations):.1f}s ({sum(durations)/60:.1f}min)")
            print(f"  Avg dur:      {sum(durations)/len(durations):.1f}s")
            print(f"  Range:        {min(durations):.1f}s — {max(durations):.1f}s")

        if sample_rates:
            print(f"  Sample rates: {', '.join(f'{sr}Hz' for sr in sorted(sample_rates))}")

        if channels:
            ch_labels = {1: "mono", 2: "stereo"}
            print(f"  Channels:     {', '.join(ch_labels.get(c, f'{c}ch') for c in sorted(channels))}")

        if parsed_count > 0:
            print(f"  Sentences:    {len(sentences)} (S{min(sentences):02d}–S{max(sentences):02d})")
            print(f"  Parsed names: {parsed_count}/{len(audio_files)}")

        if corrupted:
            print(f"  ⚠ Corrupted:  {len(corrupted)}")
            for name in corrupted:
                print(f"    → {name}")

        print()

    # ─── Overall Summary ─────────────────────────────────────────────────

    print("=" * 60)
    print("  OVERALL SUMMARY")
    print("=" * 60)
    print(f"  Speakers:         {len(speaker_dirs)}")
    print(f"  Total recordings: {total_files}")
    print(f"  Total duration:   {total_duration:.1f}s ({total_duration/60:.1f}min)")
    print(f"  Formats:          {', '.join(f'{ext} ({cnt})' for ext, cnt in sorted(all_formats.items()))}")

    if all_sample_rates:
        print(f"  Sample rates:     {', '.join(f'{sr}Hz' for sr in sorted(all_sample_rates))}")

    if all_channels:
        ch_labels = {1: "mono", 2: "stereo"}
        print(f"  Channels:         {', '.join(ch_labels.get(c, f'{c}ch') for c in sorted(all_channels))}")

    if total_corrupted:
        print(f"\n  ⚠ Corrupted files: {total_corrupted}")

    # Preprocessing recommendation
    needs_preprocessing = (
        len(all_formats) > 1
        or len(all_sample_rates) > 1
        or len(all_channels) > 1
        or any(fmt != ".wav" for fmt in all_formats)
    )

    print()
    if needs_preprocessing:
        print("  ⚠ PREPROCESSING REQUIRED")
        reasons = []
        if len(all_formats) > 1 or any(fmt != ".wav" for fmt in all_formats):
            reasons.append("Mixed/non-WAV formats detected")
        if len(all_sample_rates) > 1:
            reasons.append("Multiple sample rates detected")
        if len(all_channels) > 1:
            reasons.append("Mixed mono/stereo channels detected")
        for r in reasons:
            print(f"    → {r}")
        print("  Run: python preprocess.py")
    else:
        print("  ✓ All files are consistent WAV format — minimal preprocessing needed.")

    # Warnings
    if warnings_list:
        print("\n" + "-" * 60)
        print("  WARNINGS")
        print("-" * 60)
        for w in warnings_list:
            print(f"  ⚠ {w}")

    print()


if __name__ == "__main__":
    inspect_dataset()
