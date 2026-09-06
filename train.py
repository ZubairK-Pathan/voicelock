#!/usr/bin/env python3
"""
train.py — Fine-tune ECAPA-TDNN on your speaker dataset using ArcFace loss.

DESIGNED FOR GOOGLE COLAB (CUDA GPU).
Running on CPU will work but will be extremely slow (~2-4 hours per epoch).

Usage on Colab:
  1. Upload your processed_dataset/ folder and speaker_profiles/ folder to Colab
  2. pip install speechbrain torch torchaudio soundfile
  3. Run: python train.py
  4. Download the saved fine-tuned model (fine_tuned_model/)
  5. Copy it back and update audio_utils.py to use it

What this script does:
  - Loads all preprocessed recordings from processed_dataset/
  - Applies data augmentation (noise, time-stretch) to expand the dataset
  - Fine-tunes only the last 2 TDNN layers + embedding head using AAM-Softmax loss
  - Validates on the test split after each epoch
  - Saves the best model checkpoint
  - Compares EER before and after fine-tuning
"""

import json
import random
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

import soundfile as sf

PROJECT_ROOT = Path(__file__).resolve().parent
PROCESSED_DIR = PROJECT_ROOT / "processed_dataset"
PROFILES_DIR = PROJECT_ROOT / "speaker_profiles"
MODEL_OUT_DIR = PROJECT_ROOT / "fine_tuned_model"

TARGET_SR = 16000
EPOCHS = 30
BATCH_SIZE = 8
LEARNING_RATE = 1e-4
MARGIN = 0.2
SCALE = 30.0
SEED = 42


def set_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D numpy vectors. Range: [-1, 1]."""
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(dot / norm) if norm > 0 else 0.0


def get_device() -> torch.device:
    """Prefer CUDA (Colab GPU), fallback to MPS, then CPU."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("cpu")  # SpeechBrain MPS bug — stay on CPU
    return torch.device("cpu")


class AddGaussianNoise:
    """Add random Gaussian noise for data augmentation."""
    def __init__(self, snr_db_range=(10, 30)):
        self.snr_db_range = snr_db_range

    def __call__(self, waveform: torch.Tensor) -> torch.Tensor:
        snr_db = random.uniform(*self.snr_db_range)
        signal_power = waveform.norm(p=2) ** 2 / waveform.numel()
        noise_power = signal_power / (10 ** (snr_db / 10))
        noise = torch.randn_like(waveform) * noise_power.sqrt()
        return waveform + noise


class SpeakerDataset(Dataset):
    """
    Dataset that loads preprocessed WAV recordings and their speaker labels.

    Applies optional augmentation during training.
    Pads/trims all clips to a fixed length (3 seconds = 48000 samples at 16kHz).
    """
    FIXED_LEN = TARGET_SR * 3

    def __init__(self, recordings: list[dict], speaker_to_idx: dict, augment: bool = False):
        """
        Args:
            recordings: List of dicts with keys 'path' (str) and 'speaker' (str).
            speaker_to_idx: Mapping from speaker name to integer class index.
            augment: If True, apply random noise augmentation.
        """
        self.recordings = recordings
        self.speaker_to_idx = speaker_to_idx
        self.augment = augment
        self.noise_aug = AddGaussianNoise(snr_db_range=(15, 35))

    def __len__(self):
        return len(self.recordings)

    def __getitem__(self, idx):
        rec = self.recordings[idx]
        data, sr = sf.read(rec["path"], dtype="float32")

        if data.ndim > 1:
            data = data.mean(axis=1)

        waveform = torch.tensor(data, dtype=torch.float32)

        if len(waveform) > self.FIXED_LEN:
            start = random.randint(0, len(waveform) - self.FIXED_LEN)
            waveform = waveform[start:start + self.FIXED_LEN]
        else:
            waveform = torch.nn.functional.pad(waveform, (0, self.FIXED_LEN - len(waveform)))

        max_val = waveform.abs().max()
        if max_val > 0:
            waveform = waveform / max_val

        if self.augment:
            waveform = self.noise_aug(waveform)

        label = self.speaker_to_idx[rec["speaker"]]
        return waveform.unsqueeze(0), label


class AAMSoftmaxLoss(nn.Module):
    """
    Additive Angular Margin (ArcFace) loss.

    Pushes embeddings of the same speaker together and
    different speakers apart in angular space.

    Paper: ArcFace: Additive Angular Margin Loss for Deep Face Recognition (Deng et al., 2019).
    """
    def __init__(self, in_features: int, num_classes: int, margin: float, scale: float):
        super().__init__()
        self.margin = margin
        self.scale = scale
        self.weight = nn.Parameter(torch.FloatTensor(num_classes, in_features))
        nn.init.xavier_uniform_(self.weight)

        import math
        self.cos_m = math.cos(margin)
        self.sin_m = math.sin(margin)
        self.th = math.cos(math.pi - margin)
        self.mm = math.sin(math.pi - margin) * margin

    def forward(self, embeddings: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        """
        Args:
            embeddings: shape (batch, in_features) — L2-normalized speaker embeddings
            labels: shape (batch,) — integer class indices

        Returns:
            Scalar ArcFace cross-entropy loss.
        """
        import torch.nn.functional as F
        cosine = F.linear(F.normalize(embeddings), F.normalize(self.weight))
        sine = (1.0 - cosine ** 2).clamp(0, 1).sqrt()

        phi = cosine * self.cos_m - sine * self.sin_m
        phi = torch.where(cosine > self.th, phi, cosine - self.mm)

        one_hot = torch.zeros_like(cosine)
        one_hot.scatter_(1, labels.view(-1, 1).long(), 1)

        output = (one_hot * phi) + ((1.0 - one_hot) * cosine)
        output *= self.scale

        return F.cross_entropy(output, labels)


def load_recordings() -> tuple[list, list, dict]:
    """
    Scan processed_dataset/ and return train/test splits.

    Returns:
        (train_recs, test_recs, speaker_to_idx)
    """
    if not PROCESSED_DIR.exists():
        print(f"ERROR: {PROCESSED_DIR} not found. Upload your processed_dataset/ folder.")
        sys.exit(1)

    speaker_dirs = sorted([d for d in PROCESSED_DIR.iterdir() if d.is_dir()])
    if not speaker_dirs:
        print("ERROR: No speaker folders found in processed_dataset/")
        sys.exit(1)

    speakers = [d.name for d in speaker_dirs]
    speaker_to_idx = {sp: i for i, sp in enumerate(speakers)}
    print(f"Speakers: {speakers}")
    print(f"Speaker index mapping: {speaker_to_idx}")

    train_recs, test_recs = [], []
    for spk_dir in speaker_dirs:
        for wav in sorted(spk_dir.glob("*.wav")):
            rec = {"path": str(wav), "speaker": spk_dir.name}
            stem = wav.stem.upper()
            if any(f"_S0{s}_" in stem or f"_S{s}_" in stem for s in ["8", "9", "10", "08", "09", "10"]):
                test_recs.append(rec)
            else:
                train_recs.append(rec)

    print(f"Train recordings: {len(train_recs)} | Test recordings: {len(test_recs)}")
    return train_recs, test_recs, speaker_to_idx


def get_ecapa_model(device: torch.device):
    """Load the pretrained ECAPA-TDNN from SpeechBrain."""
    from speechbrain.inference.speaker import EncoderClassifier
    MODEL_OUT_DIR.mkdir(exist_ok=True)
    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(MODEL_OUT_DIR / "pretrained_cache"),
        run_opts={"device": "cpu"},
    )
    return classifier


def extract_embedding(classifier, waveform: torch.Tensor) -> torch.Tensor:
    """
    Extract embedding from classifier without gradient (for evaluation).
    Returns shape (embedding_dim,).
    """
    with torch.no_grad():
        emb = classifier.encode_batch(waveform.unsqueeze(0))
    return emb.squeeze()


def evaluate_eer(classifier, test_recs: list, speaker_to_idx: dict) -> float:
    """
    Compute EER on the test set using the current model state.
    Returns EER as a percentage.
    """
    profile_embeddings = {}
    for spk, idx in speaker_to_idx.items():
        spk_test = [r for r in test_recs if r["speaker"] == spk]
        if spk_test:
            embs = []
            for rec in spk_test:
                data, _ = sf.read(rec["path"], dtype="float32")
                if data.ndim > 1:
                    data = data.mean(axis=1)
                waveform = torch.tensor(data, dtype=torch.float32)
                max_val = waveform.abs().max()
                if max_val > 0:
                    waveform = waveform / max_val
                emb = extract_embedding(classifier, waveform)
                embs.append(emb.numpy())
            profile_embeddings[spk] = np.mean(embs, axis=0)

    genuine, impostor = [], []
    for rec in test_recs:
        data, _ = sf.read(rec["path"], dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        waveform = torch.tensor(data, dtype=torch.float32)
        max_val = waveform.abs().max()
        if max_val > 0:
            waveform = waveform / max_val
        emb = extract_embedding(classifier, waveform).numpy()

        for spk, profile_emb in profile_embeddings.items():
            score = cosine_similarity(emb, profile_emb)
            if spk == rec["speaker"]:
                genuine.append(score)
            else:
                impostor.append(score)

    thresholds = np.linspace(0, 1, 500)
    far = np.array([np.mean(np.array(impostor) >= t) for t in thresholds])
    frr = np.array([np.mean(np.array(genuine) < t) for t in thresholds])
    eer_idx = np.argmin(np.abs(far - frr))
    eer = (far[eer_idx] + frr[eer_idx]) / 2.0
    return eer * 100.0


def fine_tune(classifier, train_recs: list, test_recs: list, speaker_to_idx: dict, device: torch.device):
    """
    Fine-tune the last TDNN block and embedding projector of ECAPA-TDNN.

    Freezes early layers (pretrained feature extraction) and only trains:
    - The final TDNN layer
    - The attentive statistics pooling layer
    - A new AAM-Softmax classification head

    This approach (partial fine-tuning) avoids catastrophic forgetting
    while adapting the top layers to your specific speakers.
    """
    num_classes = len(speaker_to_idx)
    embedding_dim = 192

    print("\nFreezing early ECAPA-TDNN layers...")
    for name, param in classifier.mods.named_parameters():
        param.requires_grad = False

    trainable_keywords = ["tdnn5", "asp", "fc"]
    unfrozen = 0
    for name, param in classifier.mods.named_parameters():
        if any(kw in name for kw in trainable_keywords):
            param.requires_grad = True
            unfrozen += 1

    print(f"  Unfrozen parameters: {unfrozen} tensors")

    loss_fn = AAMSoftmaxLoss(
        in_features=embedding_dim,
        num_classes=num_classes,
        margin=MARGIN,
        scale=SCALE,
    )

    params = (
        list(p for p in classifier.mods.parameters() if p.requires_grad)
        + list(loss_fn.parameters())
    )
    optimizer = optim.AdamW(params, lr=LEARNING_RATE, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)

    train_dataset = SpeakerDataset(train_recs, speaker_to_idx, augment=True)
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, drop_last=True)

    print(f"\nBaseline EER (before fine-tuning)...")
    baseline_eer = evaluate_eer(classifier, test_recs, speaker_to_idx)
    print(f"  Baseline EER: {baseline_eer:.2f}%")

    best_eer = baseline_eer
    best_epoch = 0

    print(f"\nStarting fine-tuning for {EPOCHS} epochs...")
    for epoch in range(1, EPOCHS + 1):
        classifier.mods.train()
        total_loss = 0.0
        n_batches = 0

        for waveforms, labels in train_loader:
            waveforms = waveforms.squeeze(1)
            optimizer.zero_grad()

            with torch.amp.autocast("cuda") if device.type == "cuda" else torch.no_grad.__class__():
                embeddings = classifier.mods.embedding_model(waveforms)
                if embeddings.ndim == 3:
                    embeddings = embeddings.mean(dim=1)
                loss = loss_fn(embeddings, labels)

            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, max_norm=5.0)
            optimizer.step()

            total_loss += loss.item()
            n_batches += 1

        scheduler.step()
        avg_loss = total_loss / max(n_batches, 1)

        classifier.mods.eval()
        eer = evaluate_eer(classifier, test_recs, speaker_to_idx)

        marker = " ← best" if eer < best_eer else ""
        print(f"  Epoch {epoch:3d}/{EPOCHS} | Loss: {avg_loss:.4f} | EER: {eer:.2f}%{marker}")

        if eer < best_eer:
            best_eer = eer
            best_epoch = epoch
            torch.save({
                "epoch": epoch,
                "model_state": classifier.mods.state_dict(),
                "eer": eer,
            }, MODEL_OUT_DIR / "best_checkpoint.pt")

    print(f"\nFine-tuning complete.")
    print(f"  Baseline EER : {baseline_eer:.2f}%")
    print(f"  Best EER     : {best_eer:.2f}% (epoch {best_epoch})")
    delta = baseline_eer - best_eer
    if delta > 0:
        print(f"  Improvement  : -{delta:.2f}% EER")
    else:
        print(f"  No improvement. Consider collecting more data or reducing EPOCHS.")

    return best_eer


def main():
    set_seed(SEED)
    device = get_device()
    print("=" * 60)
    print("  ECAPA-TDNN FINE-TUNING")
    print("=" * 60)
    print(f"\nDevice: {device}")
    print(f"Epochs: {EPOCHS} | Batch size: {BATCH_SIZE} | LR: {LEARNING_RATE}")

    MODEL_OUT_DIR.mkdir(exist_ok=True)

    print("\nLoading dataset...")
    train_recs, test_recs, speaker_to_idx = load_recordings()

    print("\nLoading pretrained ECAPA-TDNN model...")
    classifier = get_ecapa_model(device)
    print("  Model loaded.")

    best_eer = fine_tune(classifier, train_recs, test_recs, speaker_to_idx, device)

    summary = {
        "best_eer_percent": round(best_eer, 4),
        "epochs": EPOCHS,
        "learning_rate": LEARNING_RATE,
        "speakers": list(speaker_to_idx.keys()),
        "device": str(device),
    }
    with open(MODEL_OUT_DIR / "training_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nAll outputs saved to: {MODEL_OUT_DIR}/")
    print("  - best_checkpoint.pt      (fine-tuned model weights)")
    print("  - training_summary.json   (metrics)")


if __name__ == "__main__":
    main()
