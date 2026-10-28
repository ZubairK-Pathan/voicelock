#!/usr/bin/env python3
"""
Manually download the ECAPA-TDNN model to .model_cache
This avoids SpeechBrain's symlink issues on Windows.
"""

from pathlib import Path
from huggingface_hub import hf_hub_download

MODEL_DIR = Path(__file__).parent / ".model_cache"
MODEL_DIR.mkdir(exist_ok=True)

print("Downloading ECAPA-TDNN model files...")

# Download each file explicitly with local_files_only=False and cache_dir set
files = [
    "hyperparams.yaml",
    "classifier.pt",
    "mean_var_norm_layer.pt",
    "embedding_model.pt",
]

for filename in files:
    print(f"  {filename}...", end=" ", flush=True)
    try:
        hf_hub_download(
            repo_id="speechbrain/spkrec-ecapa-voxceleb",
            filename=filename,
            cache_dir=str(MODEL_DIR),
            local_files_only=False,
            force_download=False,
        )
        print("✓")
    except Exception as e:
        print(f"✗ ({e})")

print("\nDone! Model files should now be in .model_cache/")