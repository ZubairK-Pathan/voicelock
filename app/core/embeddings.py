"""
app/core/embeddings.py — Serialization, deserialization, and validation for biometric embeddings.

Guarantees:
1. Exact dimensionality enforcement (default 192 for ECAPA-TDNN).
2. Strict rejection of NaN, positive infinity, negative infinity, and non-numeric values.
3. Stable conversion to float32 NumPy arrays without altering, re-centering, or normalizing values.
4. Privacy: Embeddings and vector values are strictly excluded from logs and error messages.
"""

import json
import math
from typing import Optional, Sequence, Union
import numpy as np

DEFAULT_EMBEDDING_DIM = 192


def serialize_embedding(
    embedding: Union[np.ndarray, Sequence[float]],
    expected_dim: int = DEFAULT_EMBEDDING_DIM,
) -> str:
    """
    Serialize a 192-dimensional embedding vector to a compact JSON string.

    Args:
        embedding: A 1D NumPy array or sequence of floating-point numbers.
        expected_dim: Expected vector dimension (default: 192).

    Returns:
        JSON-encoded string representing the float list.

    Raises:
        ValueError: If embedding is invalid, non-numeric, contains non-finite values (NaN/Inf),
                    or does not match expected_dim.
    """
    if embedding is None:
        raise ValueError("Embedding cannot be None.")

    if expected_dim <= 0:
        raise ValueError(f"expected_dim must be a positive integer, got {expected_dim}.")

    if isinstance(embedding, np.ndarray):
        squeezed = embedding.squeeze()
        if squeezed.ndim != 1:
            raise ValueError(
                f"Embedding array must be 1-dimensional, got shape {embedding.shape}."
            )
        if squeezed.shape[0] != expected_dim:
            raise ValueError(
                f"Embedding dimension mismatch: expected {expected_dim}, got {squeezed.shape[0]}."
            )
        if not np.issubdtype(squeezed.dtype, np.number):
            raise ValueError("Embedding elements must be numeric.")
        if not np.isfinite(squeezed).all():
            raise ValueError("Embedding contains non-finite values (NaN or Infinity).")

        return json.dumps([float(x) for x in squeezed])

    if isinstance(embedding, (list, tuple)):
        if len(embedding) != expected_dim:
            raise ValueError(
                f"Embedding dimension mismatch: expected {expected_dim}, got {len(embedding)}."
            )
        clean_list: list[float] = []
        for idx, val in enumerate(embedding):
            if isinstance(val, bool) or not isinstance(val, (int, float, np.number)):
                raise ValueError(f"Embedding element at index {idx} is non-numeric.")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(
                    f"Embedding element at index {idx} is non-finite (NaN or Infinity)."
                )
            clean_list.append(float(val))
        return json.dumps(clean_list)

    raise ValueError(f"Unsupported embedding type: {type(embedding).__name__}.")


def deserialize_embedding(
    embedding_json: Optional[str],
    expected_dim: int = DEFAULT_EMBEDDING_DIM,
) -> Optional[np.ndarray]:
    """
    Deserialize a JSON-encoded string to a 192-dimensional float32 NumPy array.

    Args:
        embedding_json: JSON string representing a float list, or None.
        expected_dim: Expected vector dimension (default: 192).

    Returns:
        NumPy array of shape (expected_dim,) with dtype float32, or None if embedding_json is None/empty.

    Raises:
        ValueError: If JSON is malformed, not a list, contains non-numeric/non-finite values,
                    or has an incorrect dimension count.
    """
    if embedding_json is None:
        return None

    if not isinstance(embedding_json, str):
        raise ValueError("embedding_json must be a string or None.")

    clean_str = embedding_json.strip()
    if not clean_str:
        return None

    if expected_dim <= 0:
        raise ValueError(f"expected_dim must be a positive integer, got {expected_dim}.")

    try:
        parsed = json.loads(clean_str)
    except Exception as exc:
        raise ValueError("Invalid JSON in embedding payload.") from exc

    if not isinstance(parsed, list):
        raise ValueError("Embedding payload must be a JSON array.")

    if len(parsed) != expected_dim:
        raise ValueError(
            f"Embedding dimension mismatch: expected {expected_dim}, got {len(parsed)}."
        )

    out = np.empty(expected_dim, dtype=np.float32)
    for idx, val in enumerate(parsed):
        if isinstance(val, bool) or not isinstance(val, (int, float, np.number)):
            raise ValueError(f"Embedding element at index {idx} is non-numeric.")
        if math.isnan(val) or math.isinf(val):
            raise ValueError(
                f"Embedding element at index {idx} is non-finite (NaN or Infinity)."
            )
        out[idx] = np.float32(val)

    return out
