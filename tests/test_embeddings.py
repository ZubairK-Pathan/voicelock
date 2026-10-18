"""
tests/test_embeddings.py — Unit test suite for speaker embedding serialization, deserialization, and validation.

Requirements Tested:
1. Serialization/deserialization round-trip preserving float32 precision.
2. Cosine similarity equivalence between original and deserialized vectors (>= 0.999999).
3. Exact 192-dimension enforcement.
4. Rejection of NaN, +Inf, -Inf in both numpy arrays and lists.
5. Rejection of non-numeric elements (strings, booleans, None, nested structures).
6. Malformed JSON handling in deserialization.
7. Graceful handling of None and empty strings (returns None).
8. Squeezing of multidimensional inputs (e.g., shape (1, 192) -> (192,)).
9. Privacy guarantee: embedding vector values are never dumped into error messages.
"""

import math
import numpy as np
import pytest

from app.core.embeddings import (
    serialize_embedding,
    deserialize_embedding,
    DEFAULT_EMBEDDING_DIM,
)
from audio_utils import cosine_similarity


def test_roundtrip_numpy_array():
    """Verify standard float32 numpy vector serializes and deserializes accurately."""
    rng = np.random.default_rng(42)
    original = rng.normal(size=192).astype(np.float32)

    serialized = serialize_embedding(original)
    assert isinstance(serialized, str)

    deserialized = deserialize_embedding(serialized)
    assert deserialized is not None
    assert isinstance(deserialized, np.ndarray)
    assert deserialized.shape == (192,)
    assert deserialized.dtype == np.float32

    # Numerical accuracy check
    np.testing.assert_allclose(original, deserialized, rtol=1e-5, atol=1e-6)

    # Cosine similarity check (must be functionally identical)
    sim = cosine_similarity(original, deserialized)
    assert sim >= 0.999999


def test_roundtrip_python_list():
    """Verify sequence of Python floats serializes and deserializes correctly."""
    original = [float(i * 0.01) for i in range(192)]
    serialized = serialize_embedding(original)
    deserialized = deserialize_embedding(serialized)

    assert deserialized is not None
    assert deserialized.shape == (192,)
    assert deserialized.dtype == np.float32
    np.testing.assert_allclose(original, deserialized, rtol=1e-5, atol=1e-6)


def test_squeezed_input_shape():
    """Verify input shape (1, 192) or (192, 1) is accepted after squeezing."""
    vec = np.ones((1, 192), dtype=np.float32) * 0.5
    serialized = serialize_embedding(vec)
    deserialized = deserialize_embedding(serialized)

    assert deserialized is not None
    assert deserialized.shape == (192,)


def test_rejects_none_input():
    """Verify serialize_embedding rejects None."""
    with pytest.raises(ValueError, match="Embedding cannot be None"):
        serialize_embedding(None)


def test_none_or_empty_deserialization():
    """Verify deserialize_embedding returns None on None or empty string."""
    assert deserialize_embedding(None) is None
    assert deserialize_embedding("") is None
    assert deserialize_embedding("   ") is None


def test_rejects_wrong_dimensions_numpy():
    """Verify vectors with dimension != 192 are rejected."""
    short_vec = np.zeros(191, dtype=np.float32)
    with pytest.raises(ValueError, match="Embedding dimension mismatch: expected 192, got 191"):
        serialize_embedding(short_vec)

    long_vec = np.zeros(193, dtype=np.float32)
    with pytest.raises(ValueError, match="Embedding dimension mismatch: expected 192, got 193"):
        serialize_embedding(long_vec)


def test_rejects_wrong_dimensions_list():
    """Verify lists with dimension != 192 are rejected."""
    short_list = [0.1] * 191
    with pytest.raises(ValueError, match="Embedding dimension mismatch: expected 192, got 191"):
        serialize_embedding(short_list)

    long_list = [0.1] * 193
    with pytest.raises(ValueError, match="Embedding dimension mismatch: expected 192, got 193"):
        serialize_embedding(long_list)


def test_rejects_multidimensional_arrays():
    """Verify 2D matrix (e.g. 192x2) is rejected."""
    matrix = np.zeros((96, 2), dtype=np.float32)
    with pytest.raises(ValueError, match="Embedding array must be 1-dimensional"):
        serialize_embedding(matrix)


def test_rejects_nan_values():
    """Verify NaN values are rejected in numpy and list inputs."""
    vec_nan = np.ones(192, dtype=np.float32)
    vec_nan[10] = np.nan
    with pytest.raises(ValueError, match="Embedding contains non-finite values"):
        serialize_embedding(vec_nan)

    list_nan = [0.1] * 192
    list_nan[25] = float("nan")
    with pytest.raises(ValueError, match="Embedding element at index 25 is non-finite"):
        serialize_embedding(list_nan)


def test_rejects_infinity_values():
    """Verify +Inf and -Inf are rejected."""
    vec_inf = np.ones(192, dtype=np.float32)
    vec_inf[5] = np.inf
    with pytest.raises(ValueError, match="Embedding contains non-finite values"):
        serialize_embedding(vec_inf)

    vec_ninf = np.ones(192, dtype=np.float32)
    vec_ninf[15] = -np.inf
    with pytest.raises(ValueError, match="Embedding contains non-finite values"):
        serialize_embedding(vec_ninf)

    list_inf = [0.5] * 192
    list_inf[50] = float("inf")
    with pytest.raises(ValueError, match="Embedding element at index 50 is non-finite"):
        serialize_embedding(list_inf)


def test_rejects_non_numeric_elements():
    """Verify strings, booleans, and objects in list inputs are rejected."""
    list_str = [0.1] * 192
    list_str[10] = "0.5"
    with pytest.raises(ValueError, match="Embedding element at index 10 is non-numeric"):
        serialize_embedding(list_str)

    list_bool = [0.1] * 192
    list_bool[20] = True
    with pytest.raises(ValueError, match="Embedding element at index 20 is non-numeric"):
        serialize_embedding(list_bool)

    list_none = [0.1] * 192
    list_none[30] = None
    with pytest.raises(ValueError, match="Embedding element at index 30 is non-numeric"):
        serialize_embedding(list_none)


def test_deserialization_malformed_json():
    """Verify malformed JSON payload raises ValueError."""
    with pytest.raises(ValueError, match="Invalid JSON in embedding payload"):
        deserialize_embedding("{not a json array}")


def test_deserialization_not_a_list():
    """Verify JSON object that is not an array raises ValueError."""
    with pytest.raises(ValueError, match="Embedding payload must be a JSON array"):
        deserialize_embedding('{"data": [0.1, 0.2]}')


def test_deserialization_dimension_mismatch():
    """Verify JSON array with wrong length raises ValueError."""
    with pytest.raises(ValueError, match="Embedding dimension mismatch: expected 192, got 2"):
        deserialize_embedding("[0.1, 0.2]")


def test_deserialization_rejects_nan_and_inf_strings():
    """Verify deserialization rejects non-finite values in JSON."""
    # Infinity or NaN in JSON
    nan_json = "[" + ", ".join(["NaN" if i == 0 else "0.0" for i in range(192)]) + "]"
    with pytest.raises(ValueError, match="Embedding element at index 0 is non-finite"):
        deserialize_embedding(nan_json)

    inf_json = "[" + ", ".join(["Infinity" if i == 0 else "0.0" for i in range(192)]) + "]"
    with pytest.raises(ValueError, match="Embedding element at index 0 is non-finite"):
        deserialize_embedding(inf_json)


def test_deserialization_rejects_boolean_elements():
    """Verify deserialization rejects booleans in JSON array."""
    bool_json = "[" + ", ".join(["true" if i == 0 else "0.0" for i in range(192)]) + "]"
    with pytest.raises(ValueError, match="Embedding element at index 0 is non-numeric"):
        deserialize_embedding(bool_json)


def test_privacy_no_vectors_in_exceptions():
    """Verify error messages do not leak raw vector contents."""
    vec = np.full(191, 0.1234567, dtype=np.float32)
    try:
        serialize_embedding(vec)
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        msg = str(exc)
        assert "0.1234567" not in msg
        assert "expected 192" in msg
