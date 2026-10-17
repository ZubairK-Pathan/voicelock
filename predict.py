#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

from audio_utils import (
    preprocess_audio,
    load_embedding_model,
    generate_embedding,
    load_profiles,
    cosine_similarity,
    get_device,
    TARGET_SAMPLE_RATE,
)


DEFAULT_THRESHOLD = 0.25  # Conservative default for unknown speaker detection


def predict_speaker(
    audio_path: str,
    threshold: float = DEFAULT_THRESHOLD,
    classifier=None,
    profiles: dict = None,
    verbose: bool = True,
) -> dict:
    """
    Identify the speaker of an audio file.

    Args:
        audio_path: Path to the audio file
        threshold: Minimum similarity for a valid prediction
        classifier: Pre-loaded model (optional, loaded if None)
        profiles: Pre-loaded profiles (optional, loaded if None)
        verbose: Whether to print results

    Returns:
        dict with keys: predicted_speaker, similarity, all_scores, is_unknown
    """
    audio_path = Path(audio_path)

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if profiles is None:
        profiles = load_profiles()

    if not profiles:
        raise ValueError("No speaker profiles are enrolled in the system.")

    if classifier is None:
        device = get_device()
        classifier = load_embedding_model(device)

    waveform, sr = preprocess_audio(audio_path)

    embedding = generate_embedding(classifier, waveform, sr)

    scores = {}
    for speaker_name, profile_embedding in profiles.items():
        scores[speaker_name] = cosine_similarity(embedding, profile_embedding)

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    best_speaker, best_score = ranked[0]
    is_unknown = best_score < threshold

    result = {
        "predicted_speaker": "UNKNOWN" if is_unknown else best_speaker,
        "similarity": best_score,
        "all_scores": dict(ranked),
        "is_unknown": is_unknown,
        "threshold": threshold,
    }

    if verbose:
        print()
        print("=" * 50)
        print("  SPEAKER IDENTIFICATION")
        print("=" * 50)
        print(f"\n  File: {audio_path.name}")
        print()

        if is_unknown:
            print(f"  Predicted Speaker: UNKNOWN")
            print(f"  Best Similarity:   {best_score:.4f}")
            print(f"  Threshold:         {threshold:.4f}")
            print(f"  (Best match was {best_speaker}, but below threshold)")
        else:
            print(f"  Predicted Speaker: {best_speaker}")
            print(f"  Similarity:        {best_score:.4f}")

        print(f"\n  Similarity Scores:")
        for speaker, score in ranked:
            marker = " ←" if speaker == best_speaker else ""
            print(f"    {speaker:15s}: {score:.4f}{marker}")

        print()

    return result


def verify_speaker(
    audio_path: str,
    claimed_identity: str,
    threshold: float = DEFAULT_THRESHOLD,
    classifier=None,
    profiles: dict = None,
    verbose: bool = True,
) -> dict:
    """
    Verify if the speaker is who they claim to be (1-to-1 Authentication).
    
    Args:
        audio_path: Path to the audio file
        claimed_identity: The name of the speaker they claim to be
        threshold: Minimum similarity for acceptance
        classifier: Pre-loaded model
        profiles: Pre-loaded profiles
        verbose: Whether to print results
        
    Returns:
        dict with keys: is_accepted, similarity, threshold
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if profiles is None:
        profiles = load_profiles()

    if not profiles:
        raise ValueError("No speaker profiles are enrolled in the system.")
        
    if claimed_identity not in profiles:
        raise ValueError(f"Unknown claimed identity: {claimed_identity}. Registered speakers: {list(profiles.keys())}")

    if classifier is None:
        device = get_device()
        classifier = load_embedding_model(device)

    waveform, sr = preprocess_audio(audio_path)
    embedding = generate_embedding(classifier, waveform, sr)

    target_profile = profiles[claimed_identity]
    score = cosine_similarity(embedding, target_profile)
    
    is_accepted = score >= threshold

    result = {
        "is_accepted": is_accepted,
        "similarity": score,
        "threshold": threshold,
        "claimed_identity": claimed_identity
    }

    if verbose:
        print()
        print("=" * 50)
        print("  SPEAKER VERIFICATION (1-to-1)")
        print("=" * 50)
        print(f"\n  File: {audio_path.name}")
        print(f"  Claimed Identity: {claimed_identity}")
        print()
        
        if is_accepted:
            print(f"  Result:     ✅ ACCEPTED")
        else:
            print(f"  Result:     ❌ REJECTED")
            
        print(f"  Similarity: {score:.4f} (Threshold: {threshold:.4f})")
        print()

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Identify the speaker of an audio recording."
    )
    parser.add_argument("audio_path", help="Path to the audio file")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Minimum similarity for valid prediction (default: {DEFAULT_THRESHOLD})",
    )

    args = parser.parse_args()
    try:
        predict_speaker(args.audio_path, threshold=args.threshold)
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
