#!/usr/bin/env python3

import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
    classification_report,
)

from audio_utils import (
    RESULTS_DIR,
    load_profiles,
    load_embeddings,
    cosine_similarity,
)


def evaluate():
    """Evaluate the speaker identification system on test recordings."""

    print("=" * 60)
    print("  SPEAKER IDENTIFICATION — EVALUATION")
    print("=" * 60)

    # Load profiles and embeddings
    try:
        profiles = load_profiles()
        all_embeddings = load_embeddings()
    except FileNotFoundError as e:
        print(f"\n✗ {e}")
        sys.exit(1)

    speaker_names = sorted(profiles.keys())
    print(f"\nRegistered speakers: {', '.join(speaker_names)}")

    # Filter to test set only
    test_entries = [e for e in all_embeddings if e["split"] == "test"]

    if not test_entries:
        print("\n✗ No test recordings found. Check the train/test split.")
        sys.exit(1)

    print(f"Test recordings: {len(test_entries)}")
    print()

    # ─── Run Predictions ─────────────────────────────────────────────────

    y_true = []
    y_pred = []
    misclassified = []
    all_genuine_scores = []
    all_impostor_scores = []

    for entry in test_entries:
        true_speaker = entry["speaker"]
        embedding = entry["embedding"]

        # Compute similarity against all profiles
        scores = {}
        for speaker_name, profile in profiles.items():
            sim = cosine_similarity(embedding, profile)
            scores[speaker_name] = sim

            # Track genuine vs impostor scores
            if speaker_name == true_speaker:
                all_genuine_scores.append(sim)
            else:
                all_impostor_scores.append(sim)

        # Predict = highest similarity
        predicted_speaker = max(scores, key=scores.get)
        best_score = scores[predicted_speaker]

        y_true.append(true_speaker)
        y_pred.append(predicted_speaker)

        if predicted_speaker != true_speaker:
            misclassified.append({
                "file": entry["file"],
                "true_speaker": true_speaker,
                "predicted_speaker": predicted_speaker,
                "similarity": best_score,
                "all_scores": scores,
            })

    # ─── Metrics ─────────────────────────────────────────────────────────

    accuracy = accuracy_score(y_true, y_pred)
    precision = precision_score(y_true, y_pred, average="macro", zero_division=0)
    recall = recall_score(y_true, y_pred, average="macro", zero_division=0)
    f1 = f1_score(y_true, y_pred, average="macro", zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=speaker_names)

    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    incorrect = len(y_true) - correct

    print("-" * 60)
    print("  RESULTS")
    print("-" * 60)
    print(f"  Total test samples:  {len(y_true)}")
    print(f"  Correctly identified: {correct}")
    print(f"  Incorrectly identified: {incorrect}")
    print()
    print(f"  Accuracy:   {accuracy:.4f} ({accuracy * 100:.1f}%)")
    print(f"  Precision:  {precision:.4f} (macro)")
    print(f"  Recall:     {recall:.4f} (macro)")
    print(f"  F1-Score:   {f1:.4f} (macro)")

    # ─── Confusion Matrix ────────────────────────────────────────────────

    print()
    print("-" * 60)
    print("  CONFUSION MATRIX")
    print("-" * 60)

    # Print text version
    max_name_len = max(len(n) for n in speaker_names)
    header = " " * (max_name_len + 4) + "  ".join(f"{n:>{max_name_len}}" for n in speaker_names)
    print(f"  {'Predicted →':>{max_name_len + 2}}")
    print(f"  {header}")

    for i, name in enumerate(speaker_names):
        row = "  ".join(f"{cm[i][j]:>{max_name_len}}" for j in range(len(speaker_names)))
        print(f"  {name:>{max_name_len}} │ {row}")

    # Save confusion matrix image
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 6))

    im = ax.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
    ax.figure.colorbar(im, ax=ax)

    ax.set(
        xticks=np.arange(cm.shape[1]),
        yticks=np.arange(cm.shape[0]),
        xticklabels=speaker_names,
        yticklabels=speaker_names,
        xlabel="Predicted Speaker",
        ylabel="True Speaker",
        title="Speaker Identification — Confusion Matrix",
    )

    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")

    # Add text annotations
    thresh = cm.max() / 2.0
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(
                j, i, format(cm[i, j], "d"),
                ha="center", va="center",
                color="white" if cm[i, j] > thresh else "black",
                fontsize=14,
            )

    fig.tight_layout()
    cm_path = RESULTS_DIR / "confusion_matrix.png"
    fig.savefig(cm_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Confusion matrix saved: {cm_path}")

    # ─── Per-class Report ────────────────────────────────────────────────

    print()
    print("-" * 60)
    print("  PER-SPEAKER CLASSIFICATION REPORT")
    print("-" * 60)
    report = classification_report(y_true, y_pred, labels=speaker_names, zero_division=0)
    for line in report.split("\n"):
        print(f"  {line}")

    # ─── Misclassified Recordings ────────────────────────────────────────

    if misclassified:
        print()
        print("-" * 60)
        print("  MISCLASSIFIED RECORDINGS")
        print("-" * 60)
        for m in misclassified:
            print(f"\n  File: {m['file']}")
            print(f"  True:      {m['true_speaker']}")
            print(f"  Predicted: {m['predicted_speaker']} (sim: {m['similarity']:.4f})")
            print(f"  Scores:    ", end="")
            scores_str = ", ".join(f"{k}: {v:.4f}" for k, v in sorted(m["all_scores"].items()))
            print(scores_str)
    else:
        print("\n  ✓ No misclassified recordings!")

    # ─── Genuine vs. Impostor Score Analysis ─────────────────────────────

    print()
    print("-" * 60)
    print("  SIMILARITY SCORE DISTRIBUTION")
    print("-" * 60)

    if all_genuine_scores and all_impostor_scores:
        genuine = np.array(all_genuine_scores)
        impostor = np.array(all_impostor_scores)

        print(f"  Genuine scores:  mean={genuine.mean():.4f}, "
              f"std={genuine.std():.4f}, min={genuine.min():.4f}, max={genuine.max():.4f}")
        print(f"  Impostor scores: mean={impostor.mean():.4f}, "
              f"std={impostor.std():.4f}, min={impostor.min():.4f}, max={impostor.max():.4f}")

        # Suggest threshold as midpoint between worst genuine and best impostor
        gap = genuine.min() - impostor.max()
        suggested = (genuine.min() + impostor.max()) / 2

        print(f"\n  Gap between worst genuine and best impostor: {gap:.4f}")
        print(f"  Suggested unknown-speaker threshold: {suggested:.4f}")
        print("  (This is a heuristic — not a statistically calibrated threshold)")

        # Save score distribution plot
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.hist(genuine, bins=20, alpha=0.7, label="Genuine (same speaker)", color="#2196F3")
        ax.hist(impostor, bins=20, alpha=0.7, label="Impostor (different speaker)", color="#F44336")
        ax.axvline(suggested, color="#4CAF50", linestyle="--", linewidth=2, label=f"Suggested threshold ({suggested:.3f})")
        ax.set_xlabel("Cosine Similarity")
        ax.set_ylabel("Count")
        ax.set_title("Genuine vs. Impostor Similarity Distributions")
        ax.legend()
        fig.tight_layout()

        dist_path = RESULTS_DIR / "score_distribution.png"
        fig.savefig(dist_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  Score distribution saved: {dist_path}")

    print()


if __name__ == "__main__":
    evaluate()
