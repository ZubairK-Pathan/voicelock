#!/usr/bin/env python3

import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np

from audio_utils import (
    PROCESSED_DIR,
    PROFILES_DIR,
    PROFILES_FILE,
    EMBEDDINGS_FILE,
    SPLIT_INFO_FILE,
    TARGET_SAMPLE_RATE,
    get_speaker_dirs,
    get_audio_files,
    parse_filename,
    load_audio,
    normalize_audio,
    load_embedding_model,
    generate_embedding,
)



REFERENCE_SENTENCES = list(range(1, 8))  # S01–S07
TEST_SENTENCES = list(range(8, 11))       # S08–S10


def build_profiles(processed_dir: Path = PROCESSED_DIR):
    """Generate embeddings and build speaker profiles."""

    print("=" * 60)
    print("  BUILDING SPEAKER PROFILES")
    print("=" * 60)

    speaker_dirs = get_speaker_dirs(processed_dir)
    if not speaker_dirs:
        print(f"\n✗ No speaker directories in {processed_dir}")
        print("  Run 'python preprocess.py' first.")
        sys.exit(1)


    print(f"\nDevice: cpu (SpeechBrain forced to CPU for compatibility)")
    print("Loading ECAPA-TDNN model...")
    start = time.time()
    classifier = load_embedding_model()
    print(f"Model loaded in {time.time() - start:.1f}s")

    all_embeddings = []  # List of dicts: {speaker, file, sentence, repetition, embedding, split}
    profiles = {}        # speaker_name → average reference embedding
    split_summary = {}   # speaker_name → {reference_count, test_count, files}

    print(f"\nSplit: Reference=S{REFERENCE_SENTENCES[0]:02d}–S{REFERENCE_SENTENCES[-1]:02d}, "
          f"Test=S{TEST_SENTENCES[0]:02d}–S{TEST_SENTENCES[-1]:02d}")
    print()

    start = time.time()

    for speaker_dir in speaker_dirs:
        speaker_name = speaker_dir.name
        audio_files = get_audio_files(speaker_dir)

        print(f"Processing {speaker_name} ({len(audio_files)} files)...")

        reference_embeddings = []
        ref_files = []
        test_files = []
        unparsed_files = []

        for audio_file in audio_files:
            parsed = parse_filename(audio_file)

            if parsed is None:

                unparsed_files.append(audio_file.name)
                split = "reference"
                sentence = None
                repetition = None
            else:
                sentence = parsed["sentence"]
                repetition = parsed["repetition"]
                if sentence in TEST_SENTENCES:
                    split = "test"
                else:
                    split = "reference"

            # Load and generate embedding
            try:
                waveform, sr = load_audio(audio_file, TARGET_SAMPLE_RATE)
                waveform = normalize_audio(waveform)
                embedding = generate_embedding(classifier, waveform, sr)
            except Exception as e:
                print(f"  ✗ {audio_file.name} — {e}")
                continue

            entry = {
                "speaker": speaker_name,
                "file": audio_file.name,
                "filepath": str(audio_file),
                "sentence": sentence,
                "repetition": repetition,
                "split": split,
                "embedding": embedding,
            }
            all_embeddings.append(entry)

            if split == "reference":
                reference_embeddings.append(embedding)
                ref_files.append(audio_file.name)
            else:
                test_files.append(audio_file.name)

        # Build profile by averaging reference embeddings
        if reference_embeddings:
            profile = np.mean(reference_embeddings, axis=0)
            profiles[speaker_name] = profile
            print(f"  ✓ Profile: {len(reference_embeddings)} reference, "
                  f"{len(test_files)} test embeddings")
        else:
            print(f"  ⚠ No reference embeddings for {speaker_name}!")

        if unparsed_files:
            print(f"  ⚠ Could not parse {len(unparsed_files)} filenames (assigned to reference)")

        split_summary[speaker_name] = {
            "reference_count": len(ref_files),
            "test_count": len(test_files),
            "reference_files": ref_files,
            "test_files": test_files,
        }

    elapsed = time.time() - start



    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


    with open(PROFILES_FILE, "wb") as f:
        pickle.dump(profiles, f)


    with open(EMBEDDINGS_FILE, "wb") as f:
        pickle.dump(all_embeddings, f)

    # Save split info
    split_info = {
        "reference_sentences": REFERENCE_SENTENCES,
        "test_sentences": TEST_SENTENCES,
        "split_description": (
            "Sentence-disjoint split. Sentences S01-S07 (all repetitions) are used "
            "for building speaker profiles. Sentences S08-S10 (all repetitions) are "
            "held out for testing. This prevents text-dependent bias since the model "
            "never sees test sentences during profile construction."
        ),
        "speakers": split_summary,
    }
    with open(SPLIT_INFO_FILE, "w") as f:
        json.dump(split_info, f, indent=2)


    print()
    print("=" * 60)
    print("  PROFILE BUILDING SUMMARY")
    print("=" * 60)
    print(f"  Speakers:       {len(profiles)}")
    print(f"  Total embed.:   {len(all_embeddings)}")

    total_ref = sum(s["reference_count"] for s in split_summary.values())
    total_test = sum(s["test_count"] for s in split_summary.values())
    print(f"  Reference:      {total_ref}")
    print(f"  Test:           {total_test}")

    if profiles:
        embed_dim = next(iter(profiles.values())).shape[0]
        print(f"  Embedding dim:  {embed_dim}")

    print(f"  Time:           {elapsed:.1f}s")
    print()
    print(f"  Saved to:")
    print(f"    {PROFILES_FILE}")
    print(f"    {EMBEDDINGS_FILE}")
    print(f"    {SPLIT_INFO_FILE}")
    print()


if __name__ == "__main__":
    build_profiles()
