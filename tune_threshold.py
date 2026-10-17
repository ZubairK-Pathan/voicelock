#!/usr/bin/env python3
"""
tune_threshold.py — Calibrate the optimal acceptance threshold using EER analysis.

What this script does:
  1. Loads all per-recording embeddings saved by build_profiles.py
  2. Generates "genuine" scores (same speaker vs own profile)
  3. Generates "impostor" scores (different speaker vs another speaker's profile)
  4. Sweeps all possible thresholds and computes FAR / FRR at each
  5. Finds the Equal Error Rate (EER) — the threshold where FAR == FRR
  6. Plots ROC curve and DET curve
  7. Prints the optimal threshold to use in the app

Usage:
    python tune_threshold.py

Output files (in results/):
    - roc_curve.png      — ROC curve (True Accept Rate vs False Accept Rate)
    - det_curve.png      — DET curve (FRR vs FAR, standard in biometrics papers)
    - score_hist.png     — Distribution of genuine vs impostor scores
    - threshold_report.txt — Summary of EER and recommended threshold
"""

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from audio_utils import (
    PROFILES_FILE,
    EMBEDDINGS_FILE,
    RESULTS_DIR,
    load_profiles,
    load_embeddings,
    cosine_similarity,
)


def compute_scores(profiles: dict, all_embeddings: list) -> tuple[list, list]:
    """
    Compute genuine and impostor similarity scores from the saved embeddings.

    Genuine scores: each test recording vs the profile of the SAME speaker.
    Impostor scores: each test recording vs the profile of EVERY OTHER speaker.

    Returns:
        (genuine_scores, impostor_scores) — two lists of float values.
    """
    genuine_scores = []
    impostor_scores = []

    for emb_info in all_embeddings:
        speaker = emb_info["speaker"]
        embedding = emb_info["embedding"]
        split = emb_info.get("split", "test")

        if split != "test":
            continue

        for profile_name, profile_emb in profiles.items():
            score = cosine_similarity(embedding, profile_emb)
            if profile_name == speaker:
                genuine_scores.append(score)
            else:
                impostor_scores.append(score)

    return genuine_scores, impostor_scores


def compute_far_frr(genuine: list, impostor: list, thresholds: np.ndarray):
    """
    Compute False Accept Rate and False Reject Rate across all thresholds.

    FAR(t) = proportion of impostor scores >= t  (wrongly accepted)
    FRR(t) = proportion of genuine scores < t    (wrongly rejected)
    """
    genuine_arr = np.array(genuine)
    impostor_arr = np.array(impostor)

    far = np.array([np.mean(impostor_arr >= t) for t in thresholds])
    frr = np.array([np.mean(genuine_arr < t) for t in thresholds])

    return far, frr


def find_eer(far: np.ndarray, frr: np.ndarray, thresholds: np.ndarray) -> tuple[float, float]:
    """
    Find the Equal Error Rate (EER) — the point where FAR ≈ FRR.

    Returns:
        (eer_value, eer_threshold) — the EER percentage and the threshold at which it occurs.
    """
    diff = np.abs(far - frr)
    eer_idx = np.argmin(diff)
    eer_threshold = thresholds[eer_idx]
    eer_value = (far[eer_idx] + frr[eer_idx]) / 2.0
    return eer_value, eer_threshold


def plot_score_distribution(genuine: list, impostor: list, eer_threshold: float):
    """Plot histogram of genuine vs impostor score distributions."""
    fig, ax = plt.subplots(figsize=(8, 4))
    bins = np.linspace(0, 1, 50)

    ax.hist(impostor, bins=bins, alpha=0.6, color="#e53935", label=f"Impostor (n={len(impostor)})", density=True)
    ax.hist(genuine, bins=bins, alpha=0.6, color="#43a047", label=f"Genuine (n={len(genuine)})", density=True)
    ax.axvline(eer_threshold, color="navy", linestyle="--", linewidth=2,
               label=f"EER Threshold = {eer_threshold:.3f}")

    ax.set_xlabel("Cosine Similarity Score")
    ax.set_ylabel("Density")
    ax.set_title("Score Distribution: Genuine vs Impostor")
    ax.legend()
    fig.tight_layout()

    out = RESULTS_DIR / "score_hist.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


def plot_roc(far: np.ndarray, frr: np.ndarray, eer_value: float):
    """Plot ROC curve (True Accept Rate vs False Accept Rate)."""
    tar = 1.0 - frr

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot(far, tar, color="#1565c0", linewidth=2, label="ROC Curve")
    ax.plot([0, 1], [0, 1], color="gray", linestyle="--", linewidth=1, label="Random Classifier")
    ax.scatter([eer_value], [1 - eer_value], color="red", zorder=5, s=80,
               label=f"EER = {eer_value * 100:.2f}%")

    ax.set_xlabel("False Accept Rate (FAR)")
    ax.set_ylabel("True Accept Rate (TAR = 1 - FRR)")
    ax.set_title("ROC Curve — Speaker Verification")
    ax.legend()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.tight_layout()

    out = RESULTS_DIR / "roc_curve.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


def plot_det(far: np.ndarray, frr: np.ndarray, eer_value: float):
    """Plot DET curve (Detection Error Tradeoff — standard in biometrics papers)."""
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot(far * 100, frr * 100, color="#6a1b9a", linewidth=2, label="DET Curve")
    ax.plot([eer_value * 100], [eer_value * 100], "ro", markersize=10,
            label=f"EER = {eer_value * 100:.2f}%")

    ax.set_xlabel("False Accept Rate (%)")
    ax.set_ylabel("False Reject Rate (%)")
    ax.set_title("DET Curve — Speaker Verification")
    ax.legend()
    fig.tight_layout()

    out = RESULTS_DIR / "det_curve.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


def main():
    RESULTS_DIR.mkdir(exist_ok=True)

    print("=" * 60)
    print("  THRESHOLD CALIBRATION (EER Analysis)")
    print("=" * 60)

    if not PROFILES_FILE.exists():
        print("ERROR: profiles.pkl not found. Run 'python build_profiles.py' first.")
        sys.exit(1)
    if not EMBEDDINGS_FILE.exists():
        print("ERROR: all_embeddings.pkl not found. Run 'python build_profiles.py' first.")
        sys.exit(1)

    print("\nLoading profiles and embeddings...")
    profiles = load_profiles()
    all_embeddings = load_embeddings()

    print(f"  Registered speakers: {list(profiles.keys())}")
    print(f"  Total saved embeddings: {len(all_embeddings)}")

    print("\nComputing genuine and impostor scores...")
    genuine, impostor = compute_scores(profiles, all_embeddings)

    print(f"  Genuine pairs:  {len(genuine)}")
    print(f"  Impostor pairs: {len(impostor)}")

    if len(genuine) == 0 or len(impostor) == 0:
        print("\nERROR: Not enough test data to compute EER.")
        print("Make sure build_profiles.py saved test-set embeddings in all_embeddings.pkl.")
        sys.exit(1)

    thresholds = np.linspace(0.0, 1.0, 1000)
    far, frr = compute_far_frr(genuine, impostor, thresholds)
    eer_value, eer_threshold = find_eer(far, frr, thresholds)

    print(f"\n  Genuine scores  — mean: {np.mean(genuine):.4f}, std: {np.std(genuine):.4f}")
    print(f"  Impostor scores — mean: {np.mean(impostor):.4f}, std: {np.std(impostor):.4f}")

    print("\nGenerating plots...")
    plot_score_distribution(genuine, impostor, eer_threshold)
    plot_roc(far, frr, eer_value)
    plot_det(far, frr, eer_value)

    report_lines = [
        "=" * 60,
        "  THRESHOLD CALIBRATION REPORT",
        "=" * 60,
        f"  Registered speakers : {list(profiles.keys())}",
        f"  Genuine pairs       : {len(genuine)}",
        f"  Impostor pairs      : {len(impostor)}",
        "",
        f"  Genuine  mean score : {np.mean(genuine):.4f}",
        f"  Impostor mean score : {np.mean(impostor):.4f}",
        f"  Score gap           : {np.mean(genuine) - np.mean(impostor):.4f}",
        "",
        f"  Equal Error Rate (EER)    : {eer_value * 100:.2f}%",
        f"  Optimal EER Threshold     : {eer_threshold:.4f}",
        "",
        "  Recommendation:",
        f"    Set DEFAULT_THRESHOLD = {eer_threshold:.2f} in predict.py",
        "    (This is the scientifically calibrated threshold where",
        "     FAR and FRR are equal — not a guess.)",
        "=" * 60,
    ]

    print()
    for line in report_lines:
        print(line)

    report_path = RESULTS_DIR / "threshold_report.txt"
    report_path.write_text("\n".join(report_lines))
    print(f"\n  Full report saved to: {report_path}")


if __name__ == "__main__":
    main()
